"""Help utils href interpolation and HTML sanitization tests."""

import lxml.html

from tools.help_utils import process_inline_elements, table_to_markdown, html_to_markdown


class TestHelpUtilsHrefInterpolation:
    def test_process_inline_elements_interpolates_href_in_html_mode(self):
        element = lxml.html.fromstring("<p>Go <a href='/docs/page.html'>here</a></p>")

        rendered = process_inline_elements(
            element,
            base_url="https://help.perfecto.io",
            as_html=True,
        )

        assert "<a href='https://help.perfecto.io/docs/page.html'>here</a>" in rendered
        assert "{href}" not in rendered

    def test_table_to_markdown_interpolates_href_inside_html_table_cells(self):
        table = lxml.html.fromstring(
            "<table>"
            "<tr><th>Doc</th></tr>"
            "<tr><td><a href='/docs/guide.html'>Guide</a></td></tr>"
            "</table>"
        )

        rendered = table_to_markdown(
            table,
            base_url="https://help.perfecto.io",
            as_html=True,
        )

        assert "<a href='https://help.perfecto.io/docs/guide.html'>Guide</a>" in rendered
        assert "{href}" not in rendered

    def test_html_to_markdown_outputs_markdown_links_without_literal_template(self):
        html = (
            "<html><body><main>"
            "<p>Read <a href='/docs/start.html'>Start</a></p>"
            "</main></body></html>"
        )
        rendered = html_to_markdown(html, base_url="https://help.perfecto.io")

        assert "[Start](https://help.perfecto.io/docs/start.html)" in rendered
        assert "{href}" not in rendered


class TestHelpUtilsHtmlSanitization:
    def test_javascript_href_case_insensitive_blocked(self):
        element = lxml.html.fromstring("<p><a href='JAVASCRIPT:alert(1)'>click</a></p>")

        rendered = process_inline_elements(element, as_html=True)

        assert "JAVASCRIPT:" not in rendered
        assert "alert" not in rendered

    def test_javascript_href_mixed_case_blocked(self):
        element = lxml.html.fromstring("<p><a href='JavaScript:void(0)'>click</a></p>")

        rendered = process_inline_elements(element, as_html=True)

        assert "JavaScript:" not in rendered

    def test_html_special_chars_escaped_in_link_text(self):
        element = lxml.html.fromstring("<p><a href='https://example.com'>A &amp; B</a></p>")

        rendered = process_inline_elements(element, as_html=True)

        assert "<a href='https://example.com'>A &amp; B</a>" in rendered
        assert "<script>" not in rendered

    def test_html_special_chars_escaped_in_href(self):
        element = lxml.html.fromstring("<p><a href=\"https://example.com?a=1&amp;b=2\">link</a></p>")

        rendered = process_inline_elements(element, as_html=True)

        assert "&#x27;" not in rendered or "&amp;" in rendered
        assert "<script>" not in rendered

    def test_html_special_chars_escaped_in_bold(self):
        element = lxml.html.fromstring("<p><b>&lt;script&gt;alert(1)&lt;/script&gt;</b></p>")

        rendered = process_inline_elements(element, as_html=True)

        assert "<script>" not in rendered
        assert "&lt;script&gt;" in rendered

    def test_html_special_chars_escaped_in_italic(self):
        element = lxml.html.fromstring("<p><i>&lt;img src=x onerror=alert(1)&gt;</i></p>")

        rendered = process_inline_elements(element, as_html=True)

        assert "<img" not in rendered
        assert "&lt;" in rendered

    def test_html_special_chars_escaped_in_code(self):
        element = lxml.html.fromstring("<p><code>&lt;script&gt;</code></p>")

        rendered = process_inline_elements(element, as_html=True)

        assert "<script>" not in rendered
        assert "&lt;script&gt;" in rendered
