from shorts_maker.crop import CropPlan, center_plan, crop_size, fill_gaps, smooth_track


def test_crop_size_landscape_and_portrait():
    assert crop_size(1920, 1080) == (606, 1080)
    assert crop_size(1080, 1920) == (1080, 1920)
    assert crop_size(1000, 1000) == (562, 1000)


def test_center_plan_expression_is_constant():
    plan = center_plan(1920, 1080)
    assert plan.x_expr() == str((1920 - 606) // 2)
    assert plan.filter().startswith("crop=606:1080:")


def test_fill_gaps():
    assert fill_gaps([(0, None), (1, 10.0), (2, None)]) == [(0, 10.0), (1, 10.0), (2, 10.0)]
    assert fill_gaps([(0, None)]) is None


def test_smooth_track_ignores_jitter():
    samples = [(i * 0.25, 960 + (15 if i % 2 else -15)) for i in range(40)]
    kf = smooth_track(samples, 1920, 606, deadzone=0.08)
    assert len(kf) == 1
    assert abs(kf[0][1] - (960 - 303)) <= 15


def test_smooth_track_follows_sustained_move_and_clamps():
    samples = [(i * 0.25, 600.0) for i in range(20)] + [(5 + i * 0.25, 1900.0) for i in range(20)]
    kf = smooth_track(samples, 1920, 606, deadzone=0.08)
    xs = [x for _, x in kf]
    assert xs[0] == 297.0
    assert xs[-1] == 1920 - 606  # am rechten Rand begrenzt
    assert all(b[0] > a[0] for a, b in zip(kf, kf[1:]))


def test_large_jump_becomes_hard_cut_at_first_detection():
    samples = [(i * 0.25, 400.0) for i in range(20)] + [(5 + i * 0.25, 1500.0) for i in range(20)]
    kf = smooth_track(samples, 1920, 606)
    (t_a, x_a), (t_b, x_b) = kf[-2], kf[-1]
    assert t_a == 5.0  # erster Sample nach dem Sprung, nicht verzögert
    assert t_b - t_a < 0.01
    assert x_a != x_b


def test_small_move_is_smooth_pan():
    samples = [(i * 0.25, 900.0) for i in range(20)] + [(5 + i * 0.25, 1150.0) for i in range(20)]
    kf = smooth_track(samples, 1920, 606)
    assert kf[-1][0] - kf[-2][0] > 0.3


def test_single_outlier_does_not_move_camera():
    samples = [(i * 0.25, 960.0) for i in range(20)]
    samples[10] = (2.5, 100.0)
    assert len(smooth_track(samples, 1920, 606)) == 1


def test_x_expr_piecewise_linear():
    plan = CropPlan(1920, 1080, 606, 1080, 0, [(0.0, 100.0), (2.0, 100.0), (2.5, 500.0)], "face")
    expr = plan.x_expr()
    assert expr.startswith("if(lt(t,2.000),100.0,if(lt(t,2.500),100.0+(400.0)*(t-2.000)/0.500,500.0))")
