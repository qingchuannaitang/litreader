"""DeepGaitLab review: token estimate recalibrated on the real Mac run (offline arithmetic only)."""
from litreader.estimate import RATIO, estimate
from litreader.project import session as ps

ACT = {"judge": (62939, 8288), "writer_main": (22054, 9713), "vision": (17120, 2987), "lens": (3066, 1546)}


def within(est, act, tol=0.15):
    return abs(est - act) <= tol * act


def test_estimate_matches_deepgaitlab_actuals_when_call_counts_match():
    # the real run made 15 judge/vision calls (figures were split; fixed in the figure commit)
    est = estimate({"pages": 20, "chars": 38458, "figures": 9}, {"writer", "judge", "vision"}, cached_parse=True)
    w = est["roles"]["writer"]
    assert within(w["in"], ACT["writer_main"][0]) and within(w["out"], ACT["writer_main"][1])
    per_judge = int(38458 * RATIO["judge_in_per_char"])
    j_in_15 = per_judge * 15 + RATIO["wording_in"] + RATIO["topic_in"] + RATIO["classify_in"]
    j_out_15 = RATIO["judge_out"] * 15 + RATIO["wording_out"] + RATIO["topic_out"] + RATIO["classify_out"]
    assert within(j_in_15, ACT["judge"][0]) and within(j_out_15, ACT["judge"][1])
    v_in_9, v_out_9 = RATIO["vision_in"] * 9, RATIO["vision_out"] * 9
    assert within(v_in_9, ACT["vision"][0]) and within(v_out_9, ACT["vision"][1])
    assert est["roles"]["judge"]["in"] < ACT["judge"][0]       # fewer figures after the merge fix → fewer judge calls


def test_lens_estimate_constants():
    est_in = ACT["writer_main"][1] * ps.LENS_IN_PER_WOUT + ps.LENS_IN_FIXED + 300 * 0.7
    assert within(est_in, ACT["lens"][0]) and within(ps.LENS_OUT, ACT["lens"][1])


def test_judge_output_estimate_matches_third_run_with_nine_figures():
    # 3rd Mac run (c69a7ad): 9 figures → judge 46,273 in / 8,382 out; old estimate said 5,390 out (−36%)
    est = estimate({"pages": 20, "chars": 38458, "figures": 9}, {"writer", "judge", "vision"}, cached_parse=True)
    assert within(est["roles"]["judge"]["out"], 8382)
