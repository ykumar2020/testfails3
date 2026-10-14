"""Create paper figures directly from the frozen testFAILS3 run artifact."""
from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch


ROOT = Path(__file__).resolve().parents[1]
RUN_PATH = ROOT / "data" / "runs" / "20261013T040244Z.json"
OUT = Path(__file__).resolve().parent / "figures"
OUT.mkdir(parents=True, exist_ok=True)


def load_run() -> dict:
    return json.loads(RUN_PATH.read_text(encoding="utf-8"))


def score_figure(run: dict) -> None:
    model = next(item for item in run["models"] if item["provider"] == "openai")
    results = model["results"]
    labels = [
        "Dialogue", "Productivity", "CS education", "Multilingual", "Coding",
        "App development", "Security", "Context", "Accessibility", "Multimodal",
        "Agent planning", "Emotional response", "Search", "Robot safety",
    ]
    scores = [100 * result["score"] for result in results]
    colors = ["#147A38" if score == 100 else "#A56800" if score > 0 else "#A32C23" for score in scores]

    fig, ax = plt.subplots(figsize=(7.2, 4.35))
    positions = list(range(len(labels)))
    ax.barh(positions, scores, color=colors, edgecolor="white", linewidth=0.6)
    ax.set_yticks(positions, labels, fontsize=8)
    ax.invert_yaxis()
    ax.set_xlim(0, 106)
    ax.set_xticks([0, 25, 50, 75, 100])
    ax.set_xlabel("Case score (%)", fontsize=9)
    ax.grid(axis="x", color="#D7DCE3", linewidth=0.7)
    ax.set_axisbelow(True)
    for y, score in zip(positions, scores):
        ax.text(max(score + 1.2, 2.0), y, f"{score:.0f}", va="center", fontsize=7.5)
    for spine in ax.spines.values():
        spine.set_visible(False)
    fig.tight_layout()
    fig.savefig(OUT / "component_scores.pdf", bbox_inches="tight")
    fig.savefig(OUT / "component_scores.png", dpi=240, bbox_inches="tight")
    plt.close(fig)


def architecture_figure() -> None:
    fig, ax = plt.subplots(figsize=(7.2, 2.6))
    ax.set_xlim(0, 12)
    ax.set_ylim(0, 3.2)
    ax.axis("off")
    boxes = [
        (0.25, "Versioned\ncase suite", "#EAF0FF"),
        (2.65, "Configured\nmodel APIs", "#F4EAFE"),
        (5.05, "Assertions +\ncoverage", "#E9F7EE"),
        (7.45, "Hashed run\nartifact", "#FFF2D9"),
        (9.85, "Dashboard\n+ JSON API", "#FFE9E7"),
    ]
    for x, label, color in boxes:
        patch = FancyBboxPatch((x, 1.25), 1.9, 1.05, boxstyle="round,pad=0.08,rounding_size=0.08", facecolor=color, edgecolor="#233143", linewidth=1.0)
        ax.add_patch(patch)
        ax.text(x + 0.95, 1.77, label, ha="center", va="center", fontsize=9, weight="bold")
    for x in (2.25, 4.65, 7.05, 9.45):
        ax.annotate("", xy=(x + 0.35, 1.77), xytext=(x, 1.77), arrowprops={"arrowstyle": "->", "lw": 1.4, "color": "#233143"})
    ax.annotate("official Arena snapshots\n(separate context, not score)", xy=(8.4, 1.2), xytext=(8.4, 0.25), ha="center", fontsize=8, color="#33445A", arrowprops={"arrowstyle": "->", "lw": 1.0, "color": "#33445A"})
    ax.text(6, 2.85, "testFAILS3 evidence flow", ha="center", va="center", fontsize=12, weight="bold", color="#182433")
    fig.tight_layout()
    fig.savefig(OUT / "architecture.pdf", bbox_inches="tight")
    fig.savefig(OUT / "architecture.png", dpi=240, bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    frozen_run = load_run()
    score_figure(frozen_run)
    architecture_figure()
    print(f"Figures generated from {RUN_PATH}")
