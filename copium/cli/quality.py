"""Quality preservation CLI commands."""

import json

import click

from .main import main


@main.group()
def quality():
    """Quality preservation monitoring and benchmarks.

    \b
    Commands for monitoring compression quality, running benchmarks,
    and managing A/B tests.

    \b
    Examples:
        copium quality status          Show quality dashboard
        copium quality benchmark       Run quality benchmark
        copium quality gate-stats      Show gate pass/fail statistics
    """
    pass


@quality.command("status")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def quality_status(output_format: str) -> None:
    """Show quality dashboard for current session.

    Displays compression quality metrics, gate statistics,
    CCR retrieval rates, and token savings.
    """
    from copium.quality.dashboard import QualityDashboard

    dashboard = QualityDashboard()

    if output_format == "json":
        snap = dashboard.get_snapshot()
        click.echo(json.dumps({
            "gate_pass_rate": snap.gate_pass_rate,
            "gate_checks_total": snap.gate_checks_total,
            "gate_passes": snap.gate_passes,
            "gate_failures": snap.gate_failures,
            "revert_reasons": snap.revert_reasons,
            "ccr_retrievals": snap.ccr_retrievals,
            "ccr_avg_latency_ms": snap.ccr_avg_latency_ms,
            "total_tokens_saved": snap.total_tokens_saved,
            "estimated_cost_saved": snap.estimated_cost_saved,
        }, indent=2))
    else:
        click.echo(dashboard.format_dashboard())


@quality.command("benchmark")
@click.option("--dataset", type=click.Choice(["all", "json", "code", "logs"]), default="all")
@click.option("--output", type=click.Path(), default=None, help="Output directory for results")
@click.option("--verbose", is_flag=True, help="Show detailed per-sample results")
def quality_benchmark(dataset: str, output: str, verbose: bool) -> None:
    """Run quality benchmark suite.

    Evaluates compression quality against thresholds:
    - ROUGE-L >= 0.85
    - IPS >= 0.95
    - CWQ >= 0.85

    \b
    Examples:
        copium quality benchmark                Run all benchmarks
        copium quality benchmark --dataset json  JSON benchmarks only
        copium quality benchmark --output ./out  Save results to directory
    """
    from copium.quality.benchmark import QualityBenchmark, generate_synthetic_samples
    from copium.quality.gate import ContentType

    benchmark = QualityBenchmark()

    # Load synthetic samples
    datasets = generate_synthetic_samples()
    for name, samples in datasets.items():
        benchmark.add_samples(name, samples)

    # Simple identity compressor for baseline demonstration
    def identity_compress(content: str) -> str:
        # In real use, this would be SmartCrusher/CodeAware/etc.
        words = content.split()
        if len(words) > 100:
            return " ".join(words[:80] + ["...", f"[{len(words) - 80} words compressed]"])
        return content

    target_datasets = None if dataset == "all" else [dataset]
    report = benchmark.run(identity_compress, compressor_name="baseline", datasets=target_datasets)

    # Display results
    click.echo("Quality Benchmark Results")
    click.echo("=" * 50)
    click.echo()

    for name, result in report.results.items():
        status_rouge = "PASS" if result.rouge_l_mean >= 0.85 else "FAIL"
        status_ips = "PASS" if result.ips_mean >= 0.95 else "FAIL"
        click.echo(f"  {name}:")
        click.echo(f"    ROUGE-L:    {result.rouge_l_mean:.3f}  (>= 0.85)  [{status_rouge}]")
        click.echo(f"    IPS:        {result.ips_mean:.3f}  (>= 0.95)  [{status_ips}]")
        click.echo(f"    Gate Pass:  {result.gate_pass_rate:.1%}")
        click.echo(f"    Samples:    {result.n_samples}")
        click.echo()

    click.echo(f"Overall ROUGE-L: {report.overall_rouge_l:.3f}")
    click.echo(f"Overall IPS:     {report.overall_ips:.3f}")
    click.echo(f"Overall CWQ:     {report.overall_cwq:.3f}")
    click.echo()

    for threshold, met in report.thresholds_met.items():
        icon = "PASS" if met else "FAIL"
        click.echo(f"  [{icon}] {threshold}")

    if output:
        benchmark.export_report(report, output)
        click.echo(f"\nResults exported to {output}/")


@quality.command("gate-stats")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text")
def gate_stats(output_format: str) -> None:
    """Show quality gate statistics.

    Displays pass/fail rates and revert reasons for the
    quality gate validation layer.
    """
    from copium.quality.gate import GateConfig, QualityGate

    gate = QualityGate()
    stats = gate.stats

    if output_format == "json":
        click.echo(json.dumps(stats, indent=2))
    else:
        click.echo("Quality Gate Configuration")
        click.echo("-" * 40)
        config = GateConfig()
        click.echo(f"  Min token savings:       {config.min_token_savings_pct}%")
        click.echo(f"  JSON keys requirement:   {config.json_keys_requirement:.0%}")
        click.echo(f"  Code sigs requirement:   {config.code_signatures_requirement:.0%}")
        click.echo(f"  Log errors requirement:  {config.log_errors_requirement:.0%}")
        click.echo(f"  Text markers requirement: {config.text_markers_requirement:.0%}")
        click.echo(f"  Min density ratio:       {config.min_density_ratio:.0%}")
        click.echo(f"  Auto-revert on failure:  {config.auto_revert_on_failure}")
        click.echo()
        click.echo("Gate Statistics (this process)")
        click.echo("-" * 40)
        click.echo(f"  Total checks:  {stats['checks_total']}")
        click.echo(f"  Passed:        {stats['checks_passed']}")
        click.echo(f"  Failed:        {stats['checks_failed']}")
        click.echo(f"  Reverts:       {stats['reverts_total']}")
        click.echo(f"  Pass rate:     {stats['pass_rate']:.1%}")


@quality.command("ab")
@click.argument("action", type=click.Choice(["status", "list"]))
def ab_test(action: str) -> None:
    """Manage A/B tests for compression quality.

    \b
    Examples:
        copium quality ab status    Show active test status
        copium quality ab list      List all active tests
    """
    from copium.quality.ab_testing import ABTestHarness

    harness = ABTestHarness()

    if action == "list":
        tests = harness.list_tests()
        if not tests:
            click.echo("No active A/B tests.")
        else:
            for test_id in tests:
                click.echo(f"  - {test_id}")
    elif action == "status":
        tests = harness.list_tests()
        if not tests:
            click.echo("No active A/B tests.")
            click.echo()
            click.echo("Start a test by enabling A/B testing in config:")
            click.echo("  copium config set ab_testing.enabled true")
        else:
            for test_id in tests:
                result = harness.get_status(test_id)
                if result:
                    click.echo(f"Test: {result.test_id}")
                    click.echo(f"  Group A accuracy: {result.group_a_accuracy:.3f}")
                    click.echo(f"  Group B accuracy: {result.group_b_accuracy:.3f}")
                    click.echo(f"  Delta: {result.delta_pct:+.1f}%")
                    click.echo(f"  P-value: {result.p_value:.4f}")
                    click.echo(f"  Significant: {result.significant}")
                    click.echo(f"  Recommendation: {result.recommendation}")
                    click.echo()
