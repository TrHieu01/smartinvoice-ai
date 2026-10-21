class AppError(Exception):
    def __init__(self, code: str, status: int = 422):
        self.code, self.status = code, status
        super().__init__(code)


ERROR_STATUS = {
    "receipt_not_found": 404,
    "version_conflict": 409,
    "idempotency_conflict": 409,
    "invalid_state": 409,
    "upload_missing": 409,
    "quota_exceeded": 429,
    "unsupported_media_type": 415,
}
