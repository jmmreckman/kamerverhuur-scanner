"""Lezen/schrijven van bestanden en mappen in een gedeelde Google Drive-map via
de service account (dezelfde credentials als de Google Sheet). De map moet
gedeeld zijn met het service-account e-mailadres (zie README)."""
from __future__ import annotations

import io
from dataclasses import dataclass

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from .config import Config
from .models import Pand

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_GOOGLE_NATIVE_PREFIX = "application/vnd.google-apps."
_MAP_MIMETYPE = "application/vnd.google-apps.folder"


@dataclass(frozen=True)
class DriveBestand:
    id: str
    naam: str
    mimetype: str
    gewijzigd_op: str
    grootte: int | None
    weergave_link: str

    @property
    def is_map(self) -> bool:
        return self.mimetype == _MAP_MIMETYPE


@dataclass(frozen=True)
class Kruimel:
    id: str
    naam: str


class DriveClient:
    def __init__(self, config: Config, pand: Pand):
        credentials = Credentials.from_service_account_file(config.google_service_account_file, scopes=_SCOPES)
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self.root_folder_id = pand.google_drive_folder_id

    def list_bestanden(self, folder_id: str | None = None) -> list[DriveBestand]:
        doel = folder_id or self.root_folder_id
        resultaat = (
            self._service.files()
            .list(
                q=f"'{doel}' in parents and trashed = false",
                fields="files(id, name, mimeType, modifiedTime, size, webViewLink)",
                orderBy="folder,name",
                pageSize=200,
            )
            .execute()
        )
        return [_naar_bestand(f) for f in resultaat.get("files", [])]

    def get_pad(self, folder_id: str | None) -> list[Kruimel]:
        """Broodkruimelpad vanaf de hoofdmap tot en met `folder_id`."""
        if not folder_id or folder_id == self.root_folder_id:
            return []
        kruimels: list[Kruimel] = []
        huidige_id = folder_id
        while huidige_id and huidige_id != self.root_folder_id:
            info = self._service.files().get(fileId=huidige_id, fields="id, name, parents").execute()
            kruimels.append(Kruimel(id=info["id"], naam=info["name"]))
            parents = info.get("parents") or []
            huidige_id = parents[0] if parents else None
        kruimels.reverse()
        return kruimels

    def maak_map(self, naam: str, folder_id: str | None = None) -> str:
        metadata = {"name": naam, "mimeType": _MAP_MIMETYPE, "parents": [folder_id or self.root_folder_id]}
        resultaat = self._service.files().create(body=metadata, fields="id").execute()
        return resultaat["id"]

    def vind_map(self, naam: str, folder_id: str | None = None) -> str | None:
        ouder = folder_id or self.root_folder_id
        q = (
            f"'{ouder}' in parents and trashed = false and mimeType = '{_MAP_MIMETYPE}' "
            f"and name = '{_escape_q(naam)}'"
        )
        resultaat = self._service.files().list(q=q, fields="files(id)", pageSize=1).execute()
        gevonden = resultaat.get("files", [])
        return gevonden[0]["id"] if gevonden else None

    def vind_of_maak_map(self, naam: str, folder_id: str | None = None) -> str:
        return self.vind_map(naam, folder_id) or self.maak_map(naam, folder_id)

    def upload_bestand(self, bestandsnaam: str, mimetype: str, inhoud: bytes, folder_id: str | None = None) -> str:
        media = MediaIoBaseUpload(io.BytesIO(inhoud), mimetype=mimetype or "application/octet-stream", resumable=False)
        metadata = {"name": bestandsnaam, "parents": [folder_id or self.root_folder_id]}
        resultaat = self._service.files().create(body=metadata, media_body=media, fields="id").execute()
        return resultaat["id"]

    def verwijder_bestand(self, file_id: str) -> None:
        self._service.files().delete(fileId=file_id).execute()

    def download_bestand(self, file_id: str) -> tuple[str, str, bytes]:
        """Downloadt een bestand. Google Docs/Sheets/Slides worden als PDF geexporteerd
        (die kun je niet als binair bestand downloaden)."""
        metadata = self._service.files().get(fileId=file_id, fields="name, mimeType").execute()
        naam = metadata["name"]
        mimetype = metadata.get("mimeType", "application/octet-stream")

        if mimetype.startswith(_GOOGLE_NATIVE_PREFIX):
            request = self._service.files().export_media(fileId=file_id, mimeType="application/pdf")
            naam += ".pdf"
            mimetype = "application/pdf"
        else:
            request = self._service.files().get_media(fileId=file_id)

        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _status, done = downloader.next_chunk()
        return naam, mimetype, buffer.getvalue()


def _escape_q(waarde: str) -> str:
    return waarde.replace("\\", "\\\\").replace("'", "\\'")


def _naar_bestand(f: dict) -> DriveBestand:
    return DriveBestand(
        id=f["id"],
        naam=f["name"],
        mimetype=f.get("mimeType", ""),
        gewijzigd_op=f.get("modifiedTime", ""),
        grootte=int(f["size"]) if f.get("size") else None,
        weergave_link=f.get("webViewLink", ""),
    )
