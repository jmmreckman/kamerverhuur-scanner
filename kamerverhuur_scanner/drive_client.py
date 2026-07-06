"""Lezen/schrijven van bestanden in een gedeelde Google Drive-map via de
service account (dezelfde credentials als de Google Sheet). De map moet
gedeeld zijn met het service-account e-mailadres (zie README)."""
from __future__ import annotations

import io
from dataclasses import dataclass

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from .config import Config

_SCOPES = ["https://www.googleapis.com/auth/drive"]
_GOOGLE_NATIVE_PREFIX = "application/vnd.google-apps."


@dataclass(frozen=True)
class DriveBestand:
    id: str
    naam: str
    mimetype: str
    gewijzigd_op: str
    grootte: int | None
    weergave_link: str


class DriveClient:
    def __init__(self, config: Config):
        credentials = Credentials.from_service_account_file(config.google_service_account_file, scopes=_SCOPES)
        self._service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self._folder_id = config.google_drive_folder_id

    def list_bestanden(self) -> list[DriveBestand]:
        resultaat = (
            self._service.files()
            .list(
                q=f"'{self._folder_id}' in parents and trashed = false",
                fields="files(id, name, mimeType, modifiedTime, size, webViewLink)",
                orderBy="name",
                pageSize=200,
            )
            .execute()
        )
        return [
            DriveBestand(
                id=f["id"],
                naam=f["name"],
                mimetype=f.get("mimeType", ""),
                gewijzigd_op=f.get("modifiedTime", ""),
                grootte=int(f["size"]) if f.get("size") else None,
                weergave_link=f.get("webViewLink", ""),
            )
            for f in resultaat.get("files", [])
        ]

    def upload_bestand(self, bestandsnaam: str, mimetype: str, inhoud: bytes) -> None:
        media = MediaIoBaseUpload(io.BytesIO(inhoud), mimetype=mimetype or "application/octet-stream", resumable=False)
        metadata = {"name": bestandsnaam, "parents": [self._folder_id]}
        self._service.files().create(body=metadata, media_body=media, fields="id").execute()

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
