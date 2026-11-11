"""Synthetic data only: public relay validation and independent-source labeling."""
import sys
import tempfile
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ccny_gps.student_public import parse_public_feed, in_service_window
from ccny_gps.student_public_browser import PublicBrowserRelay, feed_silence_seconds
from ccny_gps.models import Observation
from ccny_gps.storage import ObservationStore
from ccny_gps.status import get_status

NOW = datetime(2026, 11, 9, 18, 0, tzinfo=timezone.utc)


def ms(at):
    return int(at.timestamp() * 1000)


def payload(when=NOW, state="live", vehicles=None):
    if vehicles is None:
        vehicles = [
            {"vehicleId":"test-89","name":"Test bus",
             "lat":40.8205,"lon":-73.9495,
             "observedAt":ms(when-timedelta(seconds=5)),
             "heading":175,"status":"moving",
             "direction":"southbound","freshnessSeconds":5},
            {"vehicleId":"test-88","name":"Test bus 2",
             "lat":40.814,"lon":-73.952,
             "observedAt":ms(when-timedelta(seconds=12)),
             "heading":0,"status":"standing_at_stop"},
        ]
    return {"live":{"generatedAt":ms(when),
            "lastSuccessfulPoll":ms(when-timedelta(seconds=2)),
            "sourceState":state,"vehicles":vehicles},
            "estimates":{"experimental":True,"stops":[]}}


class PublicRelayTests(unittest.TestCase):
    def test_new_browser_session_does_not_immediately_timeout_on_old_response(self):
        session = NOW
        old = NOW - timedelta(hours=2)
        self.assertEqual(feed_silence_seconds(session, old, NOW + timedelta(seconds=2)), 2)
        self.assertEqual(feed_silence_seconds(session, old, NOW + timedelta(seconds=15)), 15)
        self.assertGreater(feed_silence_seconds(session, old, NOW + timedelta(seconds=46)), 45)

    def test_successful_feed_in_current_session_resets_watchdog(self):
        session = NOW
        good = NOW + timedelta(seconds=30)
        self.assertEqual(feed_silence_seconds(session, good, NOW + timedelta(seconds=40)), 10)
        self.assertGreater(feed_silence_seconds(session, good, NOW + timedelta(seconds=77)), 45)

    def test_public_bus_metadata_is_source_attributed_and_stored_atomically(self):
        sample=payload()
        sample["live"]["vehicles"][0].update({
            "name":"88","direction":"NB","status":"standing",
            "nextStopId":"145",
        })
        sample["live"]["vehicles"][1].update({
            "name":"<untrusted>","direction":"untrusted","status":"untrusted",
            "nextStopId":"untrusted",
        })
        snapshot=parse_public_feed(sample,NOW)
        self.assertEqual(snapshot.vehicle_details[0][1:5],("88","NB","standing","145"))
        self.assertEqual(snapshot.vehicle_details[1][1:5],(None,None,None,None))
        with tempfile.TemporaryDirectory() as tmp:
            store=ObservationStore(str(Path(tmp)/"gps.sqlite3"))
            try:
                worker=PublicBrowserRelay(store,"/fake/browser")
                self.assertEqual(worker.accept_payload(sample,NOW),2)
                data=get_status(store,NOW)
                self.assertEqual(data["source"],"student_public")
                by_id={v["vehicleId"]:v for v in data["vehicles"]}
                self.assertEqual(by_id["test-89"]["busName"],"88")
                self.assertEqual(by_id["test-89"]["reportedDirection"],"NB")
                self.assertEqual(by_id["test-89"]["reportedStatus"],"standing")
                self.assertEqual(by_id["test-89"]["reportedNextStopId"],"145")
                self.assertIsNone(by_id["test-88"]["busName"])
                # Rejected older observation must never replace newer metadata.
                older=payload(when=NOW-timedelta(seconds=3))
                older["live"]["vehicles"][0]["name"]="99"
                self.assertEqual(worker.accept_payload(older,NOW),0)
                self.assertEqual(store.latest_vehicle_context("student_public")["test-89"]["busName"],"88")
            finally:
                store.close()

    def test_student_experimental_forecasts_logged_for_future_backtest_only(self):
        sample=payload()
        sample["live"]["predictionsEnabled"]=False
        sample["estimates"]={
            "generatedAt":ms(NOW),
            "experimental":True,
            "stops":[{"stopId":"125","arrivals":[
                {"vehicleId":"test-89","direction":"NB",
                 "arrivalAt":ms(NOW+timedelta(minutes=5)),
                 "earliestAt":ms(NOW+timedelta(minutes=4)),
                 "latestAt":ms(NOW+timedelta(minutes=7))},
                {"vehicleId":"not-in-feed","direction":"SB",
                 "arrivalAt":ms(NOW+timedelta(minutes=6))}
            ]}]
        }
        snapshot=parse_public_feed(sample,NOW)
        self.assertEqual(len(snapshot.benchmark_forecasts),1)
        self.assertFalse(snapshot.benchmark_forecasts[0][-1])
        with tempfile.TemporaryDirectory() as tmp:
            store=ObservationStore(str(Path(tmp)/"gps.db"))
            try:
                worker=PublicBrowserRelay(store,"/fake/browser")
                self.assertEqual(worker.accept_payload(sample,NOW),2)
                self.assertEqual(store.count_forecast_comparisons(),1)
                # A new response in the same 30s bucket cannot multiply
                # near-identical reference forecasts into fake samples.
                later=NOW+timedelta(seconds=8)
                same_bucket=payload(when=later)
                same_bucket["live"]["predictionsEnabled"]=False
                same_bucket["estimates"]=sample["estimates"]
                self.assertEqual(worker.accept_payload(same_bucket,later),2)
                self.assertEqual(store.count_forecast_comparisons(),1)
                public=get_status(store,later)
                self.assertNotIn("arrivalAt",str(public))
                self.assertIn("No calibrated arrival estimates",public["warning"])
            finally:store.close()

    def test_malformed_student_estimates_never_inflate_benchmark(self):
        sample=payload()
        sample["estimates"]={"generatedAt":ms(NOW),"stops":[{
            "stopId":"125","arrivals":[
                {"vehicleId":"test-89","direction":"NB","arrivalAt":"not time"},
                {"vehicleId":"test-89","direction":"NB",
                 "arrivalAt":ms(NOW+timedelta(hours=5))},
                {"vehicleId":"test-89","direction":"SB",
                 "arrivalAt":ms(NOW-timedelta(minutes=5))}
            ]
        }]}
        self.assertEqual(parse_public_feed(sample,NOW).benchmark_forecasts,())

    def test_sample_is_third_party_not_official(self):
        snap=parse_public_feed(payload(),NOW)
        self.assertEqual(len(snap.observations),2)
        self.assertEqual({v.source for v in snap.observations},{"student_public"})
        self.assertEqual(snap.observations[0].observed_at,NOW-timedelta(seconds=5))

    def test_reject_stale_server_response(self):
        with self.assertRaisesRegex(ValueError,"stale"):
            parse_public_feed(payload(NOW-timedelta(minutes=3)),NOW)

    def test_stale_upstream_poll_is_transport_heartbeat_not_live_gps(self):
        p=payload()
        p["live"]["lastSuccessfulPoll"]=ms(NOW-timedelta(minutes=3))
        snapshot=parse_public_feed(p,NOW)
        self.assertEqual(snapshot.source_state,"stale")
        self.assertEqual(snapshot.observations,())
        with tempfile.TemporaryDirectory() as tmp:
            store=ObservationStore(str(Path(tmp)/"gps.sqlite3"))
            try:
                worker=PublicBrowserRelay(store,"/fake/path")
                self.assertEqual(worker.accept_payload(p,NOW),0)
                self.assertEqual(store.count_observations(),0)
                result=get_status(store,NOW)
                self.assertEqual(result["transportState"],"healthy")
                self.assertEqual(result["sourceState"],"no_data")
            finally:store.close()

    def test_expired_upstream_poll_not_promoted_to_live(self):
        later = NOW + timedelta(minutes=4)
        p = payload(when=later)
        p["live"]["lastSuccessfulPoll"] = ms(NOW)
        snapshot = parse_public_feed(p, later)
        self.assertEqual(snapshot.source_state, "stale")
        self.assertEqual(snapshot.observations, ())

    def test_reject_epoch_seconds_and_future(self):
        p=payload()
        p["live"]["generatedAt"]=int(NOW.timestamp())
        with self.assertRaises(ValueError):
            parse_public_feed(p,NOW)
        p=payload(NOW+timedelta(minutes=1))
        with self.assertRaises(ValueError):
            parse_public_feed(p,NOW)

    def test_geographic_validation_rejects_outside_ccny(self):
        p=payload()
        p["live"]["vehicles"][0]["lat"]=40.1
        snap=parse_public_feed(p,NOW)
        self.assertEqual(len(snap.observations),1)
        self.assertEqual(snap.vehicles_rejected,1)

    def test_do_not_accept_bad_heading_or_coordinates(self):
        p=payload()
        p["live"]["vehicles"][0]["heading"]=400
        p["live"]["vehicles"][1]["lon"]="not-a-number"
        snap=parse_public_feed(p,NOW)
        self.assertEqual(len(snap.observations),0)
        self.assertEqual(snap.vehicles_rejected,2)

    def test_outdated_vehicle_fix_not_current(self):
        p=payload()
        p["live"]["vehicles"][0]["observedAt"]=ms(NOW-timedelta(minutes=30))
        snap=parse_public_feed(p,NOW)
        self.assertEqual(len(snap.observations),1)
        self.assertEqual(snap.vehicles_rejected,1)

    def test_upstream_offline_state_never_becomes_live(self):
        for state in ("offline","stale","delayed","no_data"):
            with self.subTest(state=state):
                snap=parse_public_feed(payload(state=state),NOW)
                self.assertEqual(snap.observations,())

    def test_duplicate_bus_ids_are_rejected(self):
        p=payload()
        p["live"]["vehicles"][1]["vehicleId"]="test-89"
        snap=parse_public_feed(p,NOW)
        self.assertEqual(len(snap.observations),1)
        self.assertEqual(snap.vehicles_rejected,1)

    def test_unsupported_payload_rejected(self):
        for bad in (None, {}, {"live":[]}, {"live":{"vehicles":[]}}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_public_feed(bad,NOW)

    def test_service_window_only_weekday_and_scheduled_hours(self):
        self.assertTrue(in_service_window(datetime(2026,11,9,18,0,tzinfo=timezone.utc)))
        self.assertFalse(in_service_window(datetime(2026,11,8,18,0,tzinfo=timezone.utc)))
        self.assertFalse(in_service_window(datetime(2026,11,9,3,0,tzinfo=timezone.utc)))

    def test_read_once_commits_same_source_and_no_duplicate_gps(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=ObservationStore(str(Path(tmp)/"observations.sqlite3"))
            try:
                worker=PublicBrowserRelay(store,"/fake/path")
                self.assertEqual(worker.accept_payload(payload(),NOW),2)
                self.assertEqual(worker.accept_payload(payload(),NOW),0)
                status=get_status(store,NOW)
                self.assertEqual(status["source"],"student_public")
                self.assertFalse(status["independentlyVerified"])
                self.assertEqual(status["sourceState"],"live")
                self.assertEqual(status["transportState"],"healthy")
                self.assertEqual({x["locationKind"] for x in status["vehicles"]},{"third_party_observed"})
                self.assertEqual(len(status["vehicles"]),2)
            finally:store.close()

    def test_impossible_gps_jump_is_ignored_even_with_fresh_timestamp(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=ObservationStore(str(Path(tmp)/"observations.sqlite3"))
            try:
                worker=PublicBrowserRelay(store,"/fake/path")
                self.assertEqual(worker.accept_payload(payload(),NOW),2)
                later=NOW+timedelta(seconds=15)
                jumped=payload(when=later)
                jumped["live"]["vehicles"][0]["lat"]=40.85
                self.assertEqual(worker.accept_payload(jumped,later),1)
                latest={o.vehicle_id:o for o in store.latest_observations("student_public")}
                self.assertAlmostEqual(latest["test-89"].latitude,40.8205)
                self.assertEqual(store.count_observations(),3)
            finally:store.close()

    def test_duplicate_source_fix_does_not_create_new_position(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=ObservationStore(str(Path(tmp)/"observations.sqlite3"))
            try:
                worker=PublicBrowserRelay(store,"/fake/path")
                self.assertEqual(worker.accept_payload(payload(),NOW),2)
                newer=payload(when=NOW+timedelta(seconds=20))
                newer["live"]["vehicles"][0]["observedAt"]=ms(NOW-timedelta(seconds=5))
                self.assertEqual(worker.accept_payload(newer,NOW+timedelta(seconds=20)),1)
            finally:store.close()

    def test_official_live_takes_priority_over_student(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=ObservationStore(str(Path(tmp)/"gps.db"))
            try:
                worker=PublicBrowserRelay(store,"/fake/browser")
                worker.accept_payload(payload(),NOW)
                official=Observation(
                    "samsara","test-official",40.8205,-73.9495,
                    NOW-timedelta(seconds=4),NOW
                )
                store.commit_page("samsara",(official,),"official-1",polled_at=NOW)
                result=get_status(store,NOW)
                self.assertEqual(result["source"],"samsara")
                self.assertTrue(result["independentlyVerified"])
                self.assertEqual(len(result["vehicles"]),1)
            finally:store.close()

    def test_student_fallback_when_official_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=ObservationStore(str(Path(tmp)/"gps.db"))
            try:
                stale=Observation(
                    "samsara","test-official",40.8205,-73.9495,
                    NOW-timedelta(minutes=30), NOW-timedelta(minutes=30)
                )
                store.commit_page("samsara",(stale,),"old",polled_at=NOW-timedelta(minutes=30))
                PublicBrowserRelay(store,"none").accept_payload(payload(),NOW)
                self.assertEqual(get_status(store,NOW)["source"],"student_public")
            finally:store.close()

    def test_no_student_feed_keeps_original_unavailable_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=ObservationStore(str(Path(tmp)/"gps.db"))
            try:
                result=get_status(store,NOW)
                self.assertEqual(result["source"],"samsara")
                self.assertEqual(result["sourceState"],"no_data")
                self.assertEqual(result["vehicles"],[])
            finally:store.close()

if __name__=="__main__":
    unittest.main()
