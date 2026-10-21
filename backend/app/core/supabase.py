from urllib.parse import quote

import httpx

from backend.app.core.config import Settings
from backend.app.core.errors import AppError, ERROR_STATUS


class SupabaseGateway:
    """Small HTTP boundary; clients never control URLs, RPC names or storage paths."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client

    def headers(self) -> dict[str, str]:
        secret = self.settings.supabase_secret_key.get_secret_value()
        headers = {"apikey": secret}
        if secret.count(".") == 2:  # Legacy service_role JWT; new secret keys use apikey.
            headers["Authorization"] = "Bearer " + secret
        return headers

    async def request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if not self.settings.configured:
            raise AppError("service_not_configured", 503)
        headers = self.headers() | kwargs.pop("headers", {})
        try:
            response = await self.client.request(
                method,
                self.settings.supabase_url.rstrip("/") + path,
                headers=headers,
                **kwargs,
            )
        except httpx.HTTPError as exc:
            raise AppError("dependency_unavailable", 503) from exc
        return response

    async def rpc(self, name: str, data: dict):
        response = await self.request("POST", "/rest/v1/rpc/" + name, json=data)
        if response.is_error:
            try:
                code = response.json().get("message", "")
            except ValueError:
                code = ""
            if code in ERROR_STATUS or code == "invalid_request":
                raise AppError(code, ERROR_STATUS.get(code, 422))
            raise AppError("dependency_unavailable", 503)
        return response.json()

    async def user(self, token: str) -> str:
        # Auth verifies the access token server-side; no unverified JWT decoding.
        response = await self.request(
            "GET", "/auth/v1/user", headers={"Authorization": "Bearer " + token}
        )
        if response.status_code in (401, 403):
            raise AppError("invalid_token", 401)
        if response.is_error:
            raise AppError("dependency_unavailable", 503)
        from uuid import UUID

        try:
            user = response.json()
            if user.get("is_anonymous") or not user.get("email"):
                raise ValueError("unsupported user")
            return str(UUID(user["id"]))
        except (ValueError, KeyError, TypeError) as exc:
            raise AppError("invalid_token", 401) from exc

    @staticmethod
    def object_path(path: str) -> str:
        return "receipts/" + quote(path, safe="/")

    async def signed_upload(self, path: str) -> str:
        response = await self.request(
            "POST",
            "/storage/v1/object/upload/sign/" + self.object_path(path),
            json={"upsert": False},
        )
        if response.is_error:
            raise AppError("dependency_unavailable", 503)
        payload = response.json()
        token = payload.get("token")
        if not token:
            from urllib.parse import parse_qs, urlparse

            token = parse_qs(urlparse(payload.get("url", "")).query).get("token", [None])[0]
        if not token:
            raise AppError("dependency_unavailable", 503)
        return token

    async def signed_download(self, path: str) -> str:
        response = await self.request(
            "POST", "/storage/v1/object/sign/" + self.object_path(path), json={"expiresIn": 300}
        )
        if response.is_error:
            raise AppError("dependency_unavailable", 503)
        url = response.json().get("signedURL") or response.json().get("signedUrl")
        if not isinstance(url, str):
            raise AppError("dependency_unavailable", 503)
        if url.startswith("/object/"):
            url = "/storage/v1" + url
        return self.settings.supabase_url.rstrip("/") + url if url.startswith("/") else url

    async def download(self, path: str, max_bytes: int) -> bytes:
        if not self.settings.configured:
            raise AppError("service_not_configured", 503)
        url = (
            self.settings.supabase_url.rstrip("/") + "/storage/v1/object/" + self.object_path(path)
        )
        data = bytearray()
        try:
            async with self.client.stream("GET", url, headers=self.headers()) as response:
                if response.status_code in (400, 404):
                    raise AppError("upload_missing", 409)
                if response.is_error:
                    raise AppError("dependency_unavailable", 503)
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise AppError("file_too_large", 413)
        except httpx.HTTPError as exc:
            raise AppError("dependency_unavailable", 503) from exc
        return bytes(data)

    async def file_metadata(self, user: str, receipt: str) -> dict:
        response = await self.request(
            "GET",
            "/rest/v1/receipts",
            params={
                "id": "eq." + receipt,
                "user_id": "eq." + user,
                "status": "neq.deleting",
                "select": "storage_path,size_bytes,content_type,status",
            },
        )
        if response.is_error:
            raise AppError("dependency_unavailable", 503)
        records = response.json()
        if not records:
            raise AppError("receipt_not_found", 404)
        return records[0]
