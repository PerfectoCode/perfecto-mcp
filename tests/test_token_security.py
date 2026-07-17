"""Token error and repr sanitization tests."""

import pytest

from config.token import PerfectoToken, PerfectoTokenError


class TestTokenErrorSanitization:
    def test_invalid_token_error_does_not_include_token_value(self):
        leaked_token = {"token": "my-super-secret-token-value"}
        with pytest.raises(PerfectoTokenError) as exc_info:
            PerfectoToken(leaked_token, "demo")

        message = str(exc_info.value)
        assert "Invalid security token format" in message
        assert "my-super-secret-token-value" not in message

    def test_invalid_cloud_name_error_does_not_include_raw_value(self):
        leaked_cloud = {"cloud": "secret-cloud-name"}
        with pytest.raises(PerfectoTokenError) as exc_info:
            PerfectoToken("safe-token", leaked_cloud)

        message = str(exc_info.value)
        assert "Invalid cloud name format" in message
        assert "secret-cloud-name" not in message

    def test_repr_does_not_expose_token_or_cloud_name(self):
        token = PerfectoToken("my-secret-token", "my-cloud")

        token_repr = repr(token)
        assert "my-secret-token" not in token_repr
        assert "my-cloud" not in token_repr
        assert token_repr == "<PerfectoToken cloud_name=******** token=********>"
