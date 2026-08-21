from core.exif import file_number_from_stem, format_aperture, format_exposure


def test_lumix_file_number() -> None:
    assert file_number_from_stem("P1046662") == 1046662
    assert file_number_from_stem("P1056771") == 1056771
    assert file_number_from_stem("IMG_0001") == 1


def test_exposure_and_aperture_format() -> None:
    assert format_exposure(1 / 2000) == "1/2000"
    assert format_exposure(2.0) == "2 s"
    assert format_aperture(7.1) == "f/7.1"
