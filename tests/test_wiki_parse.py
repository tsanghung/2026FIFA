"""Tests for sync_fifa's content-based footballbox identification.

Covers the 2026-07-07 Wikipedia restructure failure mode: the main article
dropped to ~32 boxes (knockout only), the positional INDEX_TO_MATCH_NUM map
misfired, and knockout content was written into group-stage match numbers.
The parser now identifies each box by content; these tests pin that behaviour
without needing network access.
"""
import unittest

from bs4 import BeautifulSoup

import sync_fifa


def make_box(home, away, score, date_iso, stadium_city, goals="Report"):
    html = f"""
    <div class="footballbox">
      <div class="fdate">17 July 2026 ({date_iso})</div>
      <div class="ftime">3:00 p.m. UTC−4</div>
      <div class="fhome">{home}</div>
      <div class="fscore">{score}</div>
      <div class="faway">{away}</div>
      <div class="fgoals">{goals}</div>
      <div class="fright">{stadium_city}</div>
    </div>
    """
    return BeautifulSoup(html, 'html.parser').find('div', class_='footballbox')


def snapshot_row(home, away, date, stadium):
    return {'group_or_stage': '', 'date': date, 'time': '', 'home_team': home,
            'away_team': away, 'stadium': stadium, 'city': '', 'score': '',
            'home_goals': None, 'away_goals': None, 'status': 'Scheduled'}


class ExtractBoxFieldsTest(unittest.TestCase):
    def test_completed_match(self):
        box = make_box('Spain', 'Belgium', '2–1', '2026-07-10',
                       'AT&amp;T Stadium, Arlington')
        f = sync_fifa._extract_box_fields(box)
        self.assertEqual(f['home_team'], 'Spain')
        self.assertEqual(f['away_team'], 'Belgium')
        self.assertEqual(f['date'], '2026-07-10')
        self.assertEqual(f['stadium'], 'AT&T Stadium')
        self.assertEqual(f['city'], 'Arlington')
        self.assertEqual(f['score_cleaned'], '2-1')
        self.assertIsNone(f['dyn_num'])

    def test_scheduled_placeholder_carries_explicit_number(self):
        box = make_box('Winner Match 101', 'Winner Match 102', 'Match 104',
                       '2026-07-19', 'MetLife Stadium, East Rutherford')
        f = sync_fifa._extract_box_fields(box)
        self.assertEqual(f['dyn_num'], 104)

    def test_team_name_normalization(self):
        box = make_box('Czech Republic', 'Cabo Verde', '1–0', '2026-06-18',
                       'X, Y')
        f = sync_fifa._extract_box_fields(box)
        self.assertEqual(f['home_team'], 'Czechia')
        self.assertEqual(f['away_team'], 'Cape Verde')


class ResolveMatchNumTest(unittest.TestCase):
    def setUp(self):
        self.snapshot = {
            53: snapshot_row('Norway', 'France', '2026-06-26', 'Stade A'),
            98: snapshot_row('Spain', 'Belgium', '2026-07-10', 'AT&T Stadium'),
            101: snapshot_row('Winner Match 97', 'Winner Match 98',
                              '2026-07-14', 'Cotton Bowl'),
            104: snapshot_row('Winner Match 101', 'Winner Match 102',
                              '2026-07-19', 'MetLife Stadium'),
        }
        self.pairs = sync_fifa._build_pair_lookup(self.snapshot)

    def resolve(self, box):
        f = sync_fifa._extract_box_fields(box)
        return sync_fifa._resolve_match_num(f, self.snapshot, self.pairs)

    def test_explicit_number_wins(self):
        box = make_box('Winner Match 101', 'Winner Match 102', 'Match 104',
                       '2026-07-19', 'MetLife Stadium, East Rutherford')
        self.assertEqual(self.resolve(box), (104, 'explicit'))

    def test_confirmed_team_pair(self):
        box = make_box('Spain', 'Belgium', '2–1', '2026-07-10',
                       'AT&amp;T Stadium, Arlington')
        self.assertEqual(self.resolve(box), (98, 'teams'))

    def test_team_pair_matches_either_orientation(self):
        box = make_box('Belgium', 'Spain', '1–2', '2026-07-10',
                       'AT&amp;T Stadium, Arlington')
        self.assertEqual(self.resolve(box), (98, 'teams'))

    def test_knockout_rematch_disambiguated_by_date(self):
        # Same pairing exists twice: group meeting (M53) and a hypothetical
        # knockout rematch. The date must pick the right one.
        self.snapshot[103] = snapshot_row('France', 'Norway', '2026-07-18',
                                          'Hard Rock Stadium')
        pairs = sync_fifa._build_pair_lookup(self.snapshot)
        box = make_box('France', 'Norway', '1–0', '2026-07-18',
                       'Hard Rock Stadium, Miami Gardens')
        f = sync_fifa._extract_box_fields(box)
        self.assertEqual(
            sync_fifa._resolve_match_num(f, self.snapshot, pairs),
            (103, 'teams'))

    def test_new_round_teams_fill_undecided_slot_by_date_and_venue(self):
        # Semi-final slot still holds bracket placeholders; the box now names
        # the real teams. date+venue is the only usable key.
        box = make_box('France', 'Spain', '0–2', '2026-07-14',
                       'Cotton Bowl, Dallas')
        self.assertEqual(self.resolve(box), (101, 'date+venue'))

    def test_unresolvable_box_is_skipped(self):
        box = make_box('Brazil', 'Japan', '2–1', '2026-06-29',
                       'Somewhere, Else')
        self.assertEqual(self.resolve(box), (None, None))


if __name__ == '__main__':
    unittest.main()
