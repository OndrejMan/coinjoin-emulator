from unittest.mock import Mock


def response(
    status_code: int = 200, body: dict[str, object] | None = None, text: str = ""
) -> Mock:
    mock_response = Mock()
    mock_response.status_code = status_code
    mock_response.json.return_value = body or {}
    mock_response.text = text
    return mock_response
