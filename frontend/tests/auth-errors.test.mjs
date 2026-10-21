import assert from "node:assert/strict";
import { test } from "node:test";
import { authErrorMessage } from "../src/lib/auth-errors.ts";

test("email quota failure identifies delivery limits instead of password input", () => {
  const message = authErrorMessage(
    { code: "over_email_send_rate_limit", status: 429 },
    true,
  );
  assert.match(message, /giới hạn gửi email/);
  assert.doesNotMatch(message, /mật khẩu/);
});

test("confirmation and sender restrictions have different recovery guidance", () => {
  assert.match(
    authErrorMessage({ code: "email_not_confirmed" }, false),
    /kích hoạt/,
  );
  assert.match(
    authErrorMessage({ code: "email_address_not_authorized" }, true),
    /cấu hình gửi email/,
  );
  assert.match(authErrorMessage({ code: "weak_password" }, true), /Mật khẩu/);
});

test("unknown server errors do not expose raw message or email", () => {
  const message = authErrorMessage(
    { code: "unknown", message: "private@example.com secret" },
    true,
  );
  assert.doesNotMatch(message, /private@example|secret/);
  assert.match(authErrorMessage({ status: 429 }, true), /quá nhiều yêu cầu/);
});
