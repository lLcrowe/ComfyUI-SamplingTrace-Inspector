from scripts.benchmark_live import build_graph, summarize


def test_benchmark_graph_modes_keep_sampling_inputs_fixed():
    off = build_graph(mode="off", run_index=1, seed=42, output_prefix="off")
    advanced = build_graph(mode="advanced_influence", run_index=2, seed=42, output_prefix="advanced")

    off_sampler = off["2001"]["inputs"]
    advanced_sampler = advanced["2002"]["inputs"]
    assert not [node for node in off.values() if node["class_type"] == "ComfyTraceModel"]
    trace = next(node for node in advanced.values() if node["class_type"] == "ComfyTraceModel")
    assert trace["inputs"]["persist_tensor_stats"] is True
    for key in ("seed", "steps", "cfg", "sampler_name", "scheduler", "positive", "negative", "latent_image", "denoise"):
        assert off_sampler[key] == advanced_sampler[key]


def test_benchmark_summary_reports_paired_median_overhead():
    results = []
    for repetition, off_ms, basic_ms in ((1, 1000, 1100), (2, 2000, 1500), (3, 1000, 1050)):
        results.extend(
            [
                {
                    "mode": "off",
                    "measured": True,
                    "repetition": repetition,
                    "historyWallMs": off_ms,
                    "vramPeakMiB": 100,
                    "vramPeakDeltaMiB": 10,
                    "traceDiskBytes": 0,
                    "rgbaSha256": str(repetition),
                },
                {
                    "mode": "basic",
                    "measured": True,
                    "repetition": repetition,
                    "historyWallMs": basic_ms,
                    "vramPeakMiB": 101,
                    "vramPeakDeltaMiB": 11,
                    "traceDiskBytes": 1000,
                    "rgbaSha256": str(repetition),
                },
            ]
        )

    summary = summarize(results)

    assert summary["basic"]["pairedWallMsMedianDeltaVsOff"] == 50.0
    assert summary["basic"]["pairedWallPercentMedianVsOff"] == 5.0
