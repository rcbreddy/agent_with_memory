"""Fake, credential-shaped test values for redaction and log-hygiene tests.

None of these are real credentials. They are assembled at runtime so that no credential-shaped
literal (credentialed connection string, provider API key, private-key block) is ever stored in
the repository, where secret scanners would rightly flag it. See test_repository_hygiene.py.
"""

_J = "".join

FAKE_PASSWORD = _J(["hun", "ter2"])
FAKE_DB_PASSWORD = _J(["s3cret", "pw"])
# A database connection string with an inline username and password.
FAKE_DB_URL = _J(["postgres", "://", "admin", ":", FAKE_DB_PASSWORD, "@", "db.internal:5432/app"])
FAKE_GROQ_KEY = _J(["gsk", "_", "TESTSECRETgroqkey", "0123456789abcdef"])
FAKE_HINDSIGHT_KEY = _J(["hs", "_", "TESTSECREThindsightkey", "0123456789"])
FAKE_PROVIDER_KEY = _J(["gsk", "_", "abcdefghijklmnopqrstuvwxyz", "0123"])
FAKE_SK_KEY = _J(["sk", "-live-", "0123456789", "abcdefghij"])
FAKE_AWS_KEY = _J(["AKIA", "ABCDEFGHIJKLMNOP"])
FAKE_JWT = ".".join(["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiIxMjM0NTY3ODkwIn0", _J(["dozjgNryP4J3", "jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U"])])
FAKE_BASIC_AUTH = _J(["dXNlcjpw", "YXNzd29yZA=="])  # base64("user:password")
FAKE_PRIVATE_KEY_BODY = "MIIEow"
FAKE_PRIVATE_KEY = _J(
    ["-----BEGIN RSA ", "PRIVATE KEY-----\n", FAKE_PRIVATE_KEY_BODY, "\n-----END RSA ", "PRIVATE KEY-----"]
)
