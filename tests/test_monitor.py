import json
import tempfile
import unittest
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import monitor  # noqa: E402


class MonitorTests(unittest.TestCase):
    def test_parse_fixture(self):
        html = (ROOT / "tests" / "fixture-promotions.html").read_text(encoding="utf-8")
        items = monitor.parse_promotions(html)
        self.assertEqual(2, len(items))
        titles = {x["title"] for x in items}
        self.assertIn("CTKM: HỆ VI SINH ĐƯỜNG RUỘT CÂN BẰNG MỞ LỐI SỐNG KHỎE", titles)
        self.assertIn("CTKM: BỀN CƠ CẤU VÙNG DOANH SỐ 2026", titles)

    def test_pdf_is_not_detail_url(self):
        self.assertEqual("", monitor.canonicalize_url("https://assets.contentstack.io/a.pdf"))

    def test_first_run_is_baseline(self):
        state = {"schemaVersion": 1, "initialized": False, "known": {}, "currentKeys": []}
        promos = [{"title": "CTKM: A", "detailUrl": ""}, {"title": "CTKM: B", "detailUrl": ""}]
        next_state, new_items, changed = monitor.reconcile(state, promos, "2026-09-14T00:00:00Z")
        self.assertTrue(next_state["initialized"])
        self.assertEqual([], new_items)
        self.assertTrue(changed)

    def test_second_run_detects_new_title(self):
        state = {"schemaVersion": 1, "initialized": False, "known": {}, "currentKeys": []}
        baseline = [{"title": "CTKM: A", "detailUrl": ""}, {"title": "CTKM: B", "detailUrl": ""}]
        state, _, _ = monitor.reconcile(state, baseline, "2026-09-14T00:00:00Z")
        current = baseline + [{"title": "CTKM: C", "detailUrl": ""}]
        state2, new_items, changed = monitor.reconcile(state, current, "2026-09-14T01:00:00Z")
        self.assertEqual(["CTKM: C"], [x["title"] for x in new_items])
        self.assertTrue(changed)
        self.assertIn(monitor.normalize_title("CTKM: C"), state2["known"])

    def test_same_title_new_url_is_not_new(self):
        state = {"schemaVersion": 1, "initialized": False, "known": {}, "currentKeys": []}
        baseline = [{"title": "CTKM: A", "detailUrl": "https://www.amway.com.vn/vn/a"}]
        state, _, _ = monitor.reconcile(state, baseline, "2026-09-14T00:00:00Z")
        current = [{"title": "CTKM: A", "detailUrl": "https://www.amway.com.vn/vn/a-v2"}]
        _, new_items, changed = monitor.reconcile(state, current, "2026-09-14T01:00:00Z")
        self.assertEqual([], new_items)
        self.assertTrue(changed)

    def test_zero_cards_fails_closed(self):
        with self.assertRaises(RuntimeError):
            monitor.parse_promotions("<h1>CHƯƠNG TRÌNH KHUYẾN MÃI</h1><p>Không có card</p>")


if __name__ == "__main__":
    unittest.main()
