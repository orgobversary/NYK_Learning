"""Build a local, explicitly synthetic five-season passing-network demonstration."""
import argparse
import json
import os
from pathlib import Path

from knicks_history.passing import aggregate_passing_edges, load_passing_edges


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=Path("fixtures/passing-demo.csv"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-authorized-real-data", action="store_true",
                        help="Accept a non-synthetic local export whose rights_basis you reviewed")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use an empty output directory")
    rows = load_passing_edges(args.input, require_synthetic=None if args.allow_authorized_real_data else True)
    edges, seasons = aggregate_passing_edges(rows)
    args.output.mkdir(parents=True)
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/nyk-passing-matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    from d3blocks import D3Blocks
    d3 = D3Blocks(support=False, verbose="error")
    d3.sankey(pd.DataFrame(edges), title="Five-season Player Passing Lab",
              filepath=str(args.output / "player-passing-sankey.html"), showfig=False,
              show_side_panel=False, show_top_panel=False, dark_mode=True,
              color_background="#07111d", figsize=[1200, 760])
    plt.style.use("dark_background")
    top = edges[:12]
    fig, ax = plt.subplots(figsize=(11, 6), layout="constrained")
    ax.barh([f"{row['source']} → {row['target']}" for row in reversed(top)],
            [row["weight"] for row in reversed(top)], color="#55a7e0")
    ax.set(title="Synthetic player-passing lab", xlabel="Passes across five seasons")
    fig.savefig(args.output / "player-passing-fallback.png", dpi=150, facecolor="#07111d")
    plt.close(fig)
    metadata = {"synthetic": all(row["synthetic"] for row in rows), "seasons": seasons,
                "input_rows": len(rows), "visual_edges": len(edges),
                "warning": "Demonstration only; not NBA player-tracking data."}
    (args.output / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    label = "SYNTHETIC METHODS LAB" if metadata["synthetic"] else "AUTHORIZED LOCAL EXPORT"
    (args.output / "index.html").write_text(f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>NYK passing lab</title><style>body{{margin:0;background:#07111d;color:#edf6ff;font:16px system-ui}}
main{{max-width:1200px;margin:auto;padding:2rem}}.badge{{color:#ffc18c;font-weight:700;letter-spacing:.12em}}
iframe{{width:100%;height:760px;border:1px solid #365067;border-radius:14px;background:#07111d}}</style></head>
<body><main><p class="badge">{label}</p><h1>Five-season player-to-player passing Sankey</h1>
<p>{seasons[0]} through {seasons[-1]}. This scaffold demonstrates the contract and visualization; its default fixture is invented and must not be described as NBA data.</p>
<iframe title="Five-season player-passing Sankey" src="player-passing-sankey.html"></iframe></main></body></html>''',
        encoding="utf-8")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
