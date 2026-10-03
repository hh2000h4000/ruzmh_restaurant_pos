# Copyright (c) 2026, RPOS and contributors
# For license information, please see license.txt

"""The bell's one list: what did not print, and what the office said (`D-303`).

Two sources, one feed, newest first, a page at a time (`D-298`, `D-301`). Each
source is asked only for as many as could reach the page asked for, so a branch
with thousands of either sends one page, read through their indexes.
"""

from restaurant_pos.utils import announcements, kitchen


def feed(branch: str, user: str, start: int = 0) -> dict:
	page = kitchen.alerts_per_page()
	start = max(0, int(start or 0))
	# Anything that lands on this page is among the first `want` of its own source.
	want = start + page + 1

	merged = sorted(
		kitchen.print_alerts(branch, want) + announcements.mine(user, want),
		key=lambda item: (str(item["at"]), item["key"]),
		reverse=True,
	)
	return {
		"items": merged[start : start + page],
		"more": len(merged) > start + page,
		"page": page,
		# Read on the server, per person — unlike a print alert, which this till
		# reads for itself (`D-299`).
		"unread_announcements": announcements.unread(user),
	}
