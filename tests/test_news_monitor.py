import unittest

from news_monitor import _candidate_mentions, _geography_match, _issue_suggestion, _make_record, FIELDS


class NewsMonitorTests(unittest.TestCase):
    def test_kew_article_is_flagged_for_review(self):
        match = _geography_match(
            "Kew planning proposal in Melbourne, Victoria",
            "Local newspaper",
            "https://example.com/story",
        )
        self.assertEqual(match, "Kew mention — verify")

    def test_kew_east_is_area_context_not_kew_proper(self):
        match = _geography_match(
            "Eastern Freeway works near Kew East",
            "Victoria's Big Build",
            "https://bigbuild.vic.gov.au/story",
        )
        self.assertEqual(match, "Kew-area context")

    def test_unrelated_kew_is_not_assumed_to_be_victorian(self):
        match = _geography_match(
            "Kew Gardens receives new award",
            "International news",
            "https://example.com/story",
        )
        self.assertEqual(match, "Uncertain — review location")

    def test_issue_suggestion_is_keyword_based(self):
        issue = _issue_suggestion("New housing development planning proposal")
        self.assertEqual(issue, "Planning and housing")

    def test_candidate_names_are_suggested_as_mentions_not_sentiment(self):
        mentions = _candidate_mentions(
            "Kew candidate Jess Wilson discussed housing with Sophie Torney."
        )
        self.assertEqual(mentions, ["Sophie Torney", "Jess Wilson"])

    def test_candidate_fields_are_present_in_news_schema(self):
        self.assertIn("candidate_mentions_suggested", FIELDS)
        self.assertIn("candidate_mentions_reviewed", FIELDS)
        self.assertIn("candidate_evidence_type", FIELDS)
        self.assertIn("candidate_public_view_summary", FIELDS)

    def test_new_record_does_not_infer_sentiment(self):
        record = _make_record(
            title="Kew local story",
            publisher="Example publisher",
            published_at="2026-11-10T00:00:00+00:00",
            source_url="https://example.com/kew",
            summary="A short article summary.",
            source_type="News article discovery",
            collection_method="Unit test",
        )
        self.assertEqual(record["article_tone"], "Not assessed")
        self.assertEqual(record["public_sentiment_evidence"], "Not assessed")
        self.assertEqual(record["review_status"], "Needs review")
        self.assertEqual(set(record.keys()), set(FIELDS))


if __name__ == "__main__":
    unittest.main()
