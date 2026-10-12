import httpx
import pytest
import respx

from escapadinha.photos import (
    SEARCH_URL, PhotoSourceError, PixabayClient, best_url, fetch_photo,
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
    respx.get(SEARCH_URL).mock(side_effect=[httpx.Response(200, json={"hits": []}),
                                            httpx.Response(200, json={"hits": [HIT]})])
    with pytest.raises(PhotoSourceError, match="No Pixabay results"):
        fetch_photo(PixabayClient("k"), "LON", "x", tmp_path)
    with pytest.raises(PhotoSourceError, match="cannot pick #3"):
        fetch_photo(PixabayClient("k"), "LON", "x", tmp_path, pick=3)


def test_missing_key_fails_fast():
    with pytest.raises(PhotoSourceError, match="PIXABAY_API_KEY"):
        PixabayClient("")
