import httpx
import pytest

from glamtool.glamglare import GlamglareApiError, GlamglareClient


def test_find_artist_uses_api_key_and_selects_exact_prefix_match():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/artists"
        assert request.url.params["name"] == "war"
        assert request.url.params["limit"] == "100"
        assert request.headers["Authorization"] == "ApiKey glamtool.test-secret"
        return httpx.Response(
            200,
            json={
                "message": "success",
                "result": [
                    {"name": "Warpaint", "instagramHandle": "warpaintwarpaintofficial"},
                    {"name": "War", "instagramHandle": "@wartheband"},
                ],
                "pagination": {"limit": 100, "nextCursor": None},
            },
        )

    client = GlamglareClient(
        "https://api.example/",
        "test-secret",
        transport=httpx.MockTransport(handler),
    )

    artist = client.find_artist("War")

    assert artist is not None
    assert artist.name == "War"
    assert artist.instagram_handle == "@wartheband"


def test_find_artist_returns_none_without_an_exact_match():
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(
            200,
            json={"message": "success", "result": [{"name": "Warpaint"}]},
        )
    )

    assert GlamglareClient("https://api.example", "secret", transport=transport).find_artist(
        "War"
    ) is None


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, json={"message": "success"}),
        httpx.Response(200, content=b"not json"),
    ],
)
def test_find_artist_rejects_invalid_responses(response):
    transport = httpx.MockTransport(lambda _request: response)
    client = GlamglareClient("https://api.example", "secret", transport=transport)

    with pytest.raises(GlamglareApiError):
        client.find_artist("War")


def test_find_artist_raises_for_http_errors():
    transport = httpx.MockTransport(
        lambda _request: httpx.Response(401, json={"message": "Authentication required"})
    )
    client = GlamglareClient("https://api.example", "secret", transport=transport)

    with pytest.raises(httpx.HTTPStatusError):
        client.find_artist("War")
