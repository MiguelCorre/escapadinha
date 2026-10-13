import httpx
import pytest
import respx

from escapadinha.photos import (
    SEARCH_URL, PhotoSourceError, PixabayClient, best_url, fetch_photo, search,
)

HIT = {
    "id": 1, "pageURL": "https://pixabay.com/photos/london-1/", "user": "ana", "user_id": 42,
    "largeImageURL": "https://pixabay.com/get/large_1280.jpg",
}


@respx.mock
def test_fetch_photo_downloads_and_records_credit(tmp_path):
    search = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json={"hits": [HIT]}))
    respx.get(HIT["largeImageURL"]).mock(return_value=httpx.Response(200, content=b"jpegbytes"))

    photo = fetch_photo(PixabayClient("k"), "LON", "London skyline", tmp_path)

    params = search.calls.last.request.url.params
    assert params["orientation"] == "vertical" and params["image_type"] == "photo"
    assert (tmp_path / "LON.jpg").read_bytes() == b"jpegbytes"
    assert photo.file_path == "LON.jpg" and photo.source == "pixabay"
    assert photo.photographer == "ana"
    assert photo.photographer_url == "https://pixabay.com/users/ana-42/"
    assert photo.source_url == HIT["pageURL"]


def test_best_url_prefers_full_hd_when_account_has_it():
    assert best_url(HIT) == HIT["largeImageURL"]
    assert best_url(HIT | {"fullHDURL": "https://pixabay.com/get/x_1920.jpg"}).endswith("_1920.jpg")


@respx.mock
def test_errors_do_not_leak_the_api_key(tmp_path):
    respx.get(SEARCH_URL).mock(return_value=httpx.Response(400, text="[ERROR 400] Invalid key"))
    with pytest.raises(PhotoSourceError) as exc:
        fetch_photo(PixabayClient("secret-key"), "LON", "London", tmp_path)
    assert "secret-key" not in str(exc.value)


@respx.mock
def test_no_results_and_bad_pick(tmp_path):
    empty = [httpx.Response(200, json={"hits": []})] * 4          # every category
    respx.get(SEARCH_URL).mock(side_effect=[*empty, httpx.Response(200, json={"hits": [HIT]})])
    with pytest.raises(PhotoSourceError, match="No Pixabay results"):
        fetch_photo(PixabayClient("k"), "LON", "x", tmp_path)
    with pytest.raises(PhotoSourceError, match="cannot pick #3"):
        fetch_photo(PixabayClient("k"), "LON", "x", tmp_path, pick=3)


def test_missing_key_fails_fast():
    with pytest.raises(PhotoSourceError, match="PIXABAY_API_KEY"):
        PixabayClient("")


@respx.mock
def test_search_prefers_travel_photos_tagged_with_the_city(tmp_path):
    """Real failure 2026-10-13: 'Brussels' returned sprouts, 'Bristol' a town in Maine."""
    def respond(request):
        category = request.url.params.get("category")
        hits = {
            "travel": [{"tags": "bristol, maine, harbour", "id": 1},
                       {"tags": "bristol, england, bridge", "id": 2}],
            None: [{"tags": "cabbage, brussels sprouts", "id": 3}],
        }.get(category, [])
        return httpx.Response(200, json={"hits": hits})
    respx.get(SEARCH_URL).mock(side_effect=respond)
    client = PixabayClient("k")
    assert [h["id"] for h in search(client, "Bristol", must="Bristol")] == [1, 2]
    assert respx.calls[0].request.url.params.get("category") == "travel"
    # No travel photo tagged with the city: fall back to the travel results, never to "sprouts".
    assert [h["id"] for h in search(client, "Bruges", must="Bruges")] == [1, 2]


@respx.mock
def test_search_without_must_takes_the_first_category_with_hits():
    respx.get(SEARCH_URL).mock(side_effect=lambda r: httpx.Response(200, json={
        "hits": [{"tags": "x", "id": 9}] if r.url.params.get("category") == "places" else []}))
    assert [h["id"] for h in search(PixabayClient("k"), "London skyline")] == [9]
