import unittest

import ntfy_alerts


def make_trade_event(
    *,
    action,
    signature,
    slot,
    utc,
    price,
    hyusd_delta,
    hyusd_pre,
    hyusd_post,
    xsol_delta,
    xsol_pre,
    xsol_post,
    log_hints,
):
    return {
        "action": action,
        "signature": signature,
        "slot": slot,
        "block_time": slot,
        "utc": utc,
        "local": utc,
        "estimated_hyusd_per_xsol": price,
        "log_hints": log_hints,
        "hyusd_pool": {
            "delta": hyusd_delta,
            "pre_amount": hyusd_pre,
            "post_amount": hyusd_post,
        },
        "xsol_pool": {
            "delta": xsol_delta,
            "pre_amount": xsol_pre,
            "post_amount": xsol_post,
        },
    }


class DummyResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b"ok"


class NtfyAlertsTest(unittest.TestCase):
    def opener(self, request, timeout=30):
        self.captured_request = request
        self.captured_timeout = timeout
        return DummyResponse()

    def header_map(self):
        return {name.lower(): value for name, value in self.captured_request.header_items()}

    def test_build_buy_alert_with_optional_setup_fields(self):
        alert = ntfy_alerts.build_buy_alert(
            local_time="2026-04-16T12:30:00-07:00",
            amount="123.45",
            spent="456.78",
            tx="abc123",
            pages_url="https://example.com/dashboard",
            setup_grade="B",
            setup_score="61.2",
            setup_expected_24h="3.4",
            setup_confidence="Medium",
            setup_reason="score cleared the bar",
        )

        self.assertEqual(alert.title, "Hylo Stability Pool setup cleared alert bar")
        self.assertEqual(
            alert.body,
            "New confirmed deployment at 2026-04-16T12:30:00-07:00\n"
            "xSOL: 123.45\n"
            "hyUSD spent: 456.78\n"
            "Setup: B • score 61.2 • exp 24h 3.4%\n"
            "Confidence: Medium\n"
            "Why: score cleared the bar\n"
            "Dashboard: https://example.com/dashboard\n"
            "Tx: https://solscan.io/tx/abc123",
        )

    def test_build_buy_alert_without_optional_setup_fields(self):
        alert = ntfy_alerts.build_buy_alert(
            local_time="now",
            amount="10",
            spent="20",
            tx="sig",
            pages_url="https://example.com",
            setup_grade="C",
        )

        self.assertNotIn("• score", alert.body)
        self.assertNotIn("• exp 24h", alert.body)
        self.assertIn("Confidence: ", alert.body)
        self.assertIn("Why: ", alert.body)

    def test_build_single_sell_alert_skips_zero_count_lines(self):
        alert = ntfy_alerts.build_sell_alert(
            sell_count="1",
            sell_time="2026-04-16T13:00:00-07:00",
            sold="5.5",
            received="6.6",
            total_sold="5.5",
            total_received="6.6",
            sale_price="1.2",
            affected_lots="1",
            closed_lots="0",
            partial_lots="0",
            tx="sig1",
            pages_url="https://example.com",
        )

        self.assertEqual(alert.title, "Hylo Stability Pool sold xSOL")
        self.assertIn("Confirmed xSOL sale at 2026-04-16T13:00:00-07:00", alert.body)
        self.assertIn("Sale price: 1.20000", alert.body)
        self.assertNotIn("Affected lots:", alert.body)
        self.assertNotIn("Closed lots:", alert.body)
        self.assertNotIn("Partial lots:", alert.body)

    def test_build_multi_sell_alert_uses_aggregate_copy(self):
        alert = ntfy_alerts.build_sell_alert(
            sell_count="3",
            sell_time="2026-04-16T14:00:00-07:00",
            sold="4.0",
            received="7.5",
            total_sold="12.0",
            total_received="22.5",
            sale_price="1.875",
            affected_lots="3",
            closed_lots="2",
            partial_lots="1",
            tx="sig2",
            pages_url="https://example.com",
        )

        self.assertEqual(alert.title, "Hylo Stability Pool recorded 3 xSOL sells")
        self.assertIn("New confirmed xSOL sells: 3", alert.body)
        self.assertIn("Total xSOL sold: 12", alert.body)
        self.assertNotIn("Total hyUSD received:", alert.body)
        self.assertNotIn("Latest hyUSD received:", alert.body)
        self.assertNotIn("Dashboard:", alert.body)
        self.assertIn("Sale price: 1.87500", alert.body)
        self.assertNotIn("Affected lots:", alert.body)
        self.assertIn("Closed lots: 2", alert.body)
        self.assertNotIn("Partial lots:", alert.body)

    def test_build_multi_sell_alert_matches_exact_multiline_body(self):
        alert = ntfy_alerts.build_sell_alert(
            sell_count="7",
            sell_time="2026-04-22T14:15:51+00:00",
            sold="52071.963574",
            received="4011.552374",
            total_sold="1175698.4589830001",
            total_received="89807.897388",
            sale_price="0.07703862306438937",
            affected_lots="1",
            closed_lots="0",
            partial_lots="1",
            tx="sig7",
            pages_url="https://colinpade.github.io/hylo-stability-pool-monitor/",
        )

        self.assertEqual(alert.title, "Hylo Stability Pool recorded 7 xSOL sells")
        self.assertEqual(
            alert.body,
            "New confirmed xSOL sells: 7\n"
            "Total xSOL sold: 1175698\n"
            "Latest sell at 2026-04-22T14:15:51+00:00\n"
            "Latest xSOL sold: 52071.963574\n"
            "Sale price: 0.07704\n"
            "Tx: https://solscan.io/tx/sig7",
        )

    def test_format_pt_time_drops_year_seconds_and_uses_pt_label(self):
        self.assertEqual(
            ntfy_alerts.format_pt_time("2026-04-22T14:15:51+00:00"),
            "7:15 AM PT",
        )

    def test_compute_target_allocation_from_event_uses_post_balances(self):
        event = make_trade_event(
            action="sell_xsol",
            signature="sell-alloc",
            slot=20,
            utc="2026-04-22T14:15:51+00:00",
            price="2.0",
            hyusd_delta="100",
            hyusd_pre="500",
            hyusd_post="600",
            xsol_delta="-50",
            xsol_pre="250",
            xsol_post="200",
            log_hints=["SwapLeverToStable"],
        )

        xsol_pct, hyusd_pct = ntfy_alerts.compute_target_allocation_from_event(event)
        self.assertEqual(str(xsol_pct.quantize(ntfy_alerts.Decimal("0.1"))), "40.0")
        self.assertEqual(str(hyusd_pct.quantize(ntfy_alerts.Decimal("0.1"))), "60.0")

    def test_compute_mirror_action_percent_for_single_buy(self):
        event = make_trade_event(
            action="buy_xsol",
            signature="buy-1",
            slot=10,
            utc="2026-04-22T10:15:51+00:00",
            price="2.0",
            hyusd_delta="-100",
            hyusd_pre="1000",
            hyusd_post="900",
            xsol_delta="50",
            xsol_pre="100",
            xsol_post="150",
            log_hints=["RebalanceStableToLever", "SwapStableToLever"],
        )

        percent = ntfy_alerts.compute_mirror_action_percent([event], action="buy_xsol")
        self.assertEqual(str(percent.quantize(ntfy_alerts.Decimal("0.1"))), "10.0")

    def test_compute_mirror_action_percent_for_batched_sells(self):
        events = [
            make_trade_event(
                action="sell_xsol",
                signature="sell-1",
                slot=20,
                utc="2026-04-22T11:00:00+00:00",
                price="2.5",
                hyusd_delta="250",
                hyusd_pre="500",
                hyusd_post="750",
                xsol_delta="-100",
                xsol_pre="1000",
                xsol_post="900",
                log_hints=["SwapLeverToStable"],
            ),
            make_trade_event(
                action="sell_xsol",
                signature="sell-2",
                slot=21,
                utc="2026-04-22T12:00:00+00:00",
                price="2.4",
                hyusd_delta="480",
                hyusd_pre="750",
                hyusd_post="1230",
                xsol_delta="-200",
                xsol_pre="900",
                xsol_post="700",
                log_hints=["SwapLeverToStable"],
            ),
        ]

        percent = ntfy_alerts.compute_mirror_action_percent(events, action="sell_xsol")
        self.assertEqual(str(percent.quantize(ntfy_alerts.Decimal("0.1"))), "30.0")

    def test_new_trade_events_returns_rows_after_previous_signature(self):
        events = [
            make_trade_event(
                action="sell_xsol",
                signature="sell-1",
                slot=20,
                utc="2026-04-22T11:00:00+00:00",
                price="2.5",
                hyusd_delta="250",
                hyusd_pre="500",
                hyusd_post="750",
                xsol_delta="-100",
                xsol_pre="1000",
                xsol_post="900",
                log_hints=["SwapLeverToStable"],
            ),
            make_trade_event(
                action="sell_xsol",
                signature="sell-2",
                slot=21,
                utc="2026-04-22T12:00:00+00:00",
                price="2.4",
                hyusd_delta="480",
                hyusd_pre="750",
                hyusd_post="1230",
                xsol_delta="-200",
                xsol_pre="900",
                xsol_post="700",
                log_hints=["SwapLeverToStable"],
            ),
        ]

        new_events = ntfy_alerts.new_trade_events(events, action="sell_xsol", prev_signature="sell-1")
        self.assertEqual([row["signature"] for row in new_events], ["sell-2"])

    def test_build_model_snapshots_replays_mirror_strategy(self):
        events = [
            make_trade_event(
                action="buy_xsol",
                signature="buy-1",
                slot=10,
                utc="2026-04-22T10:00:00+00:00",
                price="2.0",
                hyusd_delta="-100",
                hyusd_pre="1000",
                hyusd_post="900",
                xsol_delta="50",
                xsol_pre="100",
                xsol_post="150",
                log_hints=["RebalanceStableToLever", "SwapStableToLever"],
            ),
            make_trade_event(
                action="sell_xsol",
                signature="sell-1",
                slot=11,
                utc="2026-04-22T11:00:00+00:00",
                price="3.0",
                hyusd_delta="600",
                hyusd_pre="900",
                hyusd_post="1500",
                xsol_delta="-200",
                xsol_pre="1000",
                xsol_post="800",
                log_hints=["SwapLeverToStable"],
            ),
        ]

        snapshots = ntfy_alerts.build_model_snapshots(events)
        self.assertEqual(str(snapshots["buy-1"]["action_value"].quantize(ntfy_alerts.Decimal("1"))), "1000")
        self.assertEqual(str(snapshots["buy-1"]["cash"].quantize(ntfy_alerts.Decimal("1"))), "9000")
        self.assertEqual(str(snapshots["sell-1"]["action_value"].quantize(ntfy_alerts.Decimal("1"))), "300")
        self.assertEqual(str(snapshots["sell-1"]["cash"].quantize(ntfy_alerts.Decimal("1"))), "9300")
        self.assertEqual(str(snapshots["sell-1"]["xsol_value"].quantize(ntfy_alerts.Decimal("1"))), "1200")

    def test_build_mirror_buy_alert_matches_exact_body(self):
        alert = ntfy_alerts.build_mirror_buy_alert(
            mirror_percent="0.8881090224",
            target_xsol_pct="9.6855649006",
            target_hyusd_pct="90.3144350994",
            buy_time_utc="2026-04-02T13:35:42+00:00",
            entry_price="0.047529981000013474",
            tx="sig-buy",
        )

        self.assertEqual(alert.title, "Hylo Mirror: Buy 0.9% of cash")
        self.assertEqual(
            alert.body,
            "Target allocation: 10% xSOL / 90% hyUSD\n"
            "Buy time: 6:35 AM PT\n"
            "Entry price: 0.04753\n"
            "Tx: https://solscan.io/tx/sig-buy",
        )

    def test_build_mirror_sell_alert_matches_exact_body(self):
        alert = ntfy_alerts.build_mirror_sell_alert(
            mirror_percent="7.4432283294",
            target_xsol_pct="12.6147346289",
            target_hyusd_pct="87.3852653711",
            sell_time_utc="2026-04-07T23:30:42+00:00",
            sale_price="0.07113221081966029",
            tx="sig-sell",
        )

        self.assertEqual(alert.title, "Hylo Mirror: Sell 7.4% of xSOL")
        self.assertEqual(
            alert.body,
            "Target allocation: 13% xSOL / 87% hyUSD\n"
            "Sell time: 4:30 PM PT\n"
            "Sale price: 0.07113\n"
            "Tx: https://solscan.io/tx/sig-sell",
        )

    def test_build_model_buy_alert_matches_exact_body(self):
        alert = ntfy_alerts.build_model_buy_alert(
            action_usd="89.2",
            after_xsol_usd="975.4",
            after_hyusd_usd="9024.6",
            after_xsol_pct="9.754",
            after_hyusd_pct="90.246",
            target_xsol_pct="9.6855649006",
            target_hyusd_pct="90.3144350994",
            buy_time_utc="2026-04-02T13:35:42+00:00",
            entry_price="0.047529981000013474",
        )

        self.assertEqual(alert.title, "Hylo $10k Model: Buy $89 of xSOL")
        self.assertEqual(
            alert.body,
            "After trade: $975 xSOL / $9,025 hyUSD (10% / 90%)\n"
            "Target allocation: 10% xSOL / 90% hyUSD\n"
            "Buy time: 6:35 AM PT\n"
            "Entry price: 0.04753",
        )

    def test_build_model_sell_alert_matches_exact_body(self):
        alert = ntfy_alerts.build_model_sell_alert(
            action_usd="52.39644193567084",
            after_xsol_usd="651.5513562052734",
            after_hyusd_usd="9552.716016488528",
            after_xsol_pct="6.385087066111164",
            after_hyusd_pct="93.61491293388883",
            target_xsol_pct="12.6147346289",
            target_hyusd_pct="87.3852653711",
            sell_time_utc="2026-04-07T23:30:42+00:00",
            sale_price="0.07113221081966029",
        )

        self.assertEqual(alert.title, "Hylo $10k Model: Sell $52 of xSOL")
        self.assertEqual(
            alert.body,
            "After trade: $652 xSOL / $9,553 hyUSD (6% / 94%)\n"
            "Target allocation: 13% xSOL / 87% hyUSD\n"
            "Sell time: 4:30 PM PT\n"
            "Sale price: 0.07113",
        )

    def test_parse_auth_header_accepts_standard_header(self):
        self.assertEqual(
            ntfy_alerts.parse_auth_header("Authorization: Bearer secret"),
            ("Authorization", "Bearer secret"),
        )

    def test_parse_auth_header_rejects_invalid_value(self):
        with self.assertRaises(ValueError):
            ntfy_alerts.parse_auth_header("Bearer secret")

    def test_publish_alert_posts_to_topic_with_optional_auth_header(self):
        alert = ntfy_alerts.NtfyAlert(title="Title", body="Body")

        ntfy_alerts.publish_alert(
            "topic-name",
            alert,
            auth_header="Authorization: Bearer secret",
            opener=self.opener,
        )

        self.assertEqual(self.captured_request.full_url, "https://ntfy.sh/topic-name")
        self.assertEqual(self.captured_request.get_method(), "POST")
        self.assertEqual(self.captured_request.data, b"Body")
        self.assertEqual(self.captured_timeout, 30)
        headers = self.header_map()
        self.assertEqual(headers["title"], "Title")
        self.assertEqual(headers["authorization"], "Bearer secret")

    def test_main_buy_cli_sends_expected_request(self):
        ntfy_alerts.main(
            [
                "--topic",
                "buy-topic",
                "--auth-header",
                "Authorization: Bearer abc",
                "buy",
                "--local-time",
                "2026-04-16T12:30:00-07:00",
                "--amount",
                "10.0",
                "--spent",
                "20.0",
                "--tx",
                "sig-buy",
                "--pages-url",
                "https://example.com/dashboard",
                "--setup-grade",
                "A",
                "--setup-score",
                "74.1",
                "--setup-expected-24h",
                "5.3",
                "--setup-confidence",
                "High",
                "--setup-reason",
                "best setup",
            ],
            opener=self.opener,
        )

        headers = self.header_map()
        self.assertEqual(self.captured_request.full_url, "https://ntfy.sh/buy-topic")
        self.assertEqual(headers["authorization"], "Bearer abc")
        body = self.captured_request.data.decode("utf-8")
        self.assertIn("Setup: A • score 74.1 • exp 24h 5.3%", body)
        self.assertIn("Tx: https://solscan.io/tx/sig-buy", body)

    def test_main_sell_cli_falls_back_to_utc_time(self):
        ntfy_alerts.main(
            [
                "--topic",
                "sell-topic",
                "sell",
                "--sell-count",
                "2",
                "--sell-local-time",
                "",
                "--sell-utc-time",
                "2026-04-16T21:00:00+00:00",
                "--sold",
                "3.0",
                "--received",
                "4.5",
                "--total-sold",
                "6.0",
                "--total-received",
                "9.0",
                "--sale-price",
                "1.5",
                "--affected-lots",
                "2",
                "--closed-lots",
                "1",
                "--partial-lots",
                "1",
                "--tx",
                "sig-sell",
                "--pages-url",
                "https://example.com/dashboard",
            ],
            opener=self.opener,
        )

        headers = self.header_map()
        self.assertEqual(headers["title"], "Hylo Stability Pool recorded 2 xSOL sells")
        body = self.captured_request.data.decode("utf-8")
        self.assertIn("Latest sell at 2026-04-16T21:00:00+00:00", body)
        self.assertIn("Total xSOL sold: 6", body)
        self.assertIn("Sale price: 1.50000", body)
        self.assertIn("Closed lots: 1", body)
        self.assertNotIn("Total hyUSD received:", body)
        self.assertNotIn("Latest hyUSD received:", body)
        self.assertNotIn("Affected lots:", body)
        self.assertNotIn("Partial lots:", body)
        self.assertNotIn("Dashboard:", body)

    def test_main_mirror_sell_cli_sends_expected_request(self):
        ntfy_alerts.main(
            [
                "--topic",
                "mirror-topic",
                "mirror-sell",
                "--mirror-percent",
                "7.4432283294",
                "--target-xsol-pct",
                "12.6147346289",
                "--target-hyusd-pct",
                "87.3852653711",
                "--sell-time-utc",
                "2026-04-07T23:30:42+00:00",
                "--sale-price",
                "0.07113221081966029",
                "--tx",
                "sig-mirror",
            ],
            opener=self.opener,
        )

        headers = self.header_map()
        self.assertEqual(self.captured_request.full_url, "https://ntfy.sh/mirror-topic")
        self.assertEqual(headers["title"], "Hylo Mirror: Sell 7.4% of xSOL")
        self.assertEqual(
            self.captured_request.data.decode("utf-8"),
            "Target allocation: 13% xSOL / 87% hyUSD\n"
            "Sell time: 4:30 PM PT\n"
            "Sale price: 0.07113\n"
            "Tx: https://solscan.io/tx/sig-mirror",
        )

    def test_main_model_sell_cli_sends_expected_request(self):
        ntfy_alerts.main(
            [
                "--topic",
                "model-topic",
                "model-sell",
                "--action-usd",
                "52.39644193567084",
                "--after-xsol-usd",
                "651.5513562052734",
                "--after-hyusd-usd",
                "9552.716016488528",
                "--after-xsol-pct",
                "6.385087066111164",
                "--after-hyusd-pct",
                "93.61491293388883",
                "--target-xsol-pct",
                "12.6147346289",
                "--target-hyusd-pct",
                "87.3852653711",
                "--sell-time-utc",
                "2026-04-07T23:30:42+00:00",
                "--sale-price",
                "0.07113221081966029",
            ],
            opener=self.opener,
        )

        headers = self.header_map()
        self.assertEqual(self.captured_request.full_url, "https://ntfy.sh/model-topic")
        self.assertEqual(headers["title"], "Hylo $10k Model: Sell $52 of xSOL")
        self.assertEqual(
            self.captured_request.data.decode("utf-8"),
            "After trade: $652 xSOL / $9,553 hyUSD (6% / 94%)\n"
            "Target allocation: 13% xSOL / 87% hyUSD\n"
            "Sell time: 4:30 PM PT\n"
            "Sale price: 0.07113",
        )


if __name__ == "__main__":
    unittest.main()
