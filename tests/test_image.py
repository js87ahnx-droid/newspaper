import feedparser

from pipeline.collect import entry_image


def first_entry(item_xml: str):
    doc = (
        '<?xml version="1.0"?><rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">'
        f"<channel><title>t</title><item><title>x</title><link>https://a.test/1</link>{item_xml}</item></channel></rss>"
    )
    return feedparser.parse(doc.encode()).entries[0]


def test_media_content_largest_wins():
    e = first_entry(
        '<media:content url="https://img.test/s.jpg" medium="image" width="200"/>'
        '<media:content url="https://img.test/l.jpg" medium="image" width="1200"/>'
    )
    assert entry_image(e) == "https://img.test/l.jpg"


def test_media_content_video_ignored():
    e = first_entry('<media:content url="https://v.test/clip.mp4" medium="video"/>')
    assert entry_image(e) is None


def test_media_thumbnail():
    e = first_entry('<media:thumbnail url="https://img.test/t.jpg" width="240"/>')
    assert entry_image(e) == "https://img.test/t.jpg"


def test_image_enclosure():
    e = first_entry('<enclosure url="https://img.test/e.png" type="image/png" length="1"/>')
    assert entry_image(e) == "https://img.test/e.png"


def test_img_in_summary():
    e = first_entry('<description><![CDATA[<img src="https://img.test/d.jpg"/> 리드]]></description>')
    assert entry_image(e) == "https://img.test/d.jpg"


def test_no_image():
    assert entry_image(first_entry("<description>리드만</description>")) is None


def test_non_http_rejected():
    e = first_entry('<media:thumbnail url="data:image/png;base64,AAAA"/>')
    assert entry_image(e) is None
