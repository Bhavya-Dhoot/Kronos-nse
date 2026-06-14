"""Filesystem model registry for Kronos NSE checkpoints."""

from __future__ import annotations

import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

HF_TOKENIZER_REPO = "NeoQuasar/Kronos-Tokenizer-base"
HF_PREDICTOR_REPO = "NeoQuasar/Kronos-small"


class ModelRegistry:
    """Manages versioned tokenizer/predictor checkpoints on disk."""

    def __init__(self, checkpoint_dir: str | Path = "./checkpoints") -> None:
        self.root = Path(checkpoint_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "production").mkdir(parents=True, exist_ok=True)

    def _version_dir(self, version: str) -> Path:
        return self.root / version

    def _metadata_path(self, version: str) -> Path:
        return self._version_dir(version) / "metadata.json"

    def _read_metadata(self, version: str) -> dict[str, Any]:
        path = self._metadata_path(version)
        if not path.exists():
            raise FileNotFoundError(f"metadata.json not found for version {version}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _write_metadata(self, version: str, metadata: dict[str, Any]) -> None:
        path = self._metadata_path(version)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    def _generate_version(self) -> str:
        return datetime.now(UTC).strftime("v_%Y%m%d_%H%M%S")

    def register_checkpoint(
        self,
        tokenizer_path: str | Path,
        predictor_path: str | Path,
        metrics: dict[str, Any],
        version: str | None = None,
    ) -> str:
        """Copy tokenizer/predictor trees into a new version directory."""
        version = version or self._generate_version()
        vdir = self._version_dir(version)
        meta_path = self._metadata_path(version)
        if vdir.exists() and meta_path.exists():
            raise ValueError(f"Version already exists: {version}")

        tok_dst = vdir / "tokenizer"
        pred_dst = vdir / "predictor"
        tok_dst.mkdir(parents=True, exist_ok=True)
        pred_dst.mkdir(parents=True, exist_ok=True)

        if not any(tok_dst.iterdir()):
            shutil.copytree(tokenizer_path, tok_dst, dirs_exist_ok=True)
        if not any(pred_dst.iterdir()):
            shutil.copytree(predictor_path, pred_dst, dirs_exist_ok=True)

        metadata = {
            "version": version,
            "created_at": datetime.now(UTC).isoformat(),
            "metrics": metrics,
            "is_production": False,
            "promoted_at": None,
        }
        self._write_metadata(version, metadata)
        logger.info("Registered checkpoint version %s", version)
        return version

    def promote_to_production(self, version: str) -> None:
        """Atomically promote a version to checkpoints/production/.

        Uses a copy-rename-then-cleanup strategy so that a crash between
        the copy and the rename does not leave ``production/`` in a
        corrupted state. A stale ``.production_swap`` is recovered rather
        than deleted on next invoke.
        """
        src = self._version_dir(version)
        if not src.exists():
            raise FileNotFoundError(f"Version not found: {version}")

        prod = self.root / "production"
        tmp = self.root / ".production_swap"

        # Recover from a previously interrupted promote
        if tmp.exists() and not prod.exists():
            logger.info("Recovering from interrupted promote — found .production_swap")
            tmp.rename(prod)
            prod = self.root / "production"

        if tmp.exists():
            shutil.rmtree(tmp)

        shutil.copytree(src, tmp)
        metadata = self._read_metadata(version)
        metadata["is_production"] = True
        metadata["promoted_at"] = datetime.now(UTC).isoformat()
        self._write_metadata(version, metadata)
        (tmp / "metadata.json").write_text(
            json.dumps(metadata, indent=2), encoding="utf-8"
        )

        old_prod = self.root / ".production_old"
        if prod.exists():
            prod.rename(old_prod)
        tmp.rename(prod)
        if old_prod.exists():
            shutil.rmtree(old_prod)

        for v in self.get_all_versions():
            if v["version"] != version and v.get("is_production"):
                m = self._read_metadata(v["version"])
                m["is_production"] = False
                self._write_metadata(v["version"], m)

        logger.info("Promoted version %s to production", version)

    def get_production_paths(self) -> dict[str, str]:
        """Return production tokenizer/predictor paths and version id."""
        prod = self.root / "production"
        meta_path = prod / "metadata.json"
        if not meta_path.exists():
            raise FileNotFoundError("No production model registered")

        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        return {
            "tokenizer": str(prod / "tokenizer"),
            "predictor": str(prod / "predictor"),
            "version": str(metadata.get("version", "production")),
        }

    def has_production(self) -> bool:
        prod = self.root / "production"
        return (prod / "metadata.json").exists() and (prod / "tokenizer").exists()

    def get_all_versions(self) -> list[dict[str, Any]]:
        versions: list[dict[str, Any]] = []
        for entry in self.root.iterdir():
            if not entry.is_dir():
                continue
            if entry.name in {
                "production",
                ".production_swap",
            } or entry.name.startswith("."):
                continue
            meta_file = entry / "metadata.json"
            if meta_file.exists():
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                versions.append(meta)
        versions.sort(key=lambda m: m.get("created_at", ""), reverse=True)
        return versions

    def get_metrics(self, version: str) -> dict[str, Any]:
        return dict(self._read_metadata(version).get("metrics") or {})

    def compare(self, v1: str, v2: str) -> dict[str, Any]:
        m1 = self.get_metrics(v1)
        m2 = self.get_metrics(v2)
        keys = set(m1) | set(m2)
        delta: dict[str, Any] = {}
        for k in keys:
            a, b = m1.get(k), m2.get(k)
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                delta[k] = b - a
            else:
                delta[k] = {"v1": a, "v2": b}
        return {"v1": v1, "v2": v2, "delta": delta}

    def bootstrap_from_huggingface(self) -> str:
        """Download base HF weights into v_pretrained and promote.

        Not called automatically — invoke explicitly when ready to download weights.
        """
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise RuntimeError(
                "huggingface_hub is required for bootstrap_from_huggingface"
            ) from exc

        pretrained = self.root / "v_pretrained"
        tok_dir = pretrained / "tokenizer"
        pred_dir = pretrained / "predictor"
        tok_dir.mkdir(parents=True, exist_ok=True)
        pred_dir.mkdir(parents=True, exist_ok=True)

        logger.info("Downloading %s ...", HF_TOKENIZER_REPO)
        snapshot_download(repo_id=HF_TOKENIZER_REPO, local_dir=str(tok_dir))
        logger.info("Downloading %s ...", HF_PREDICTOR_REPO)
        snapshot_download(repo_id=HF_PREDICTOR_REPO, local_dir=str(pred_dir))

        version = self.register_checkpoint(
            tokenizer_path=tok_dir,
            predictor_path=pred_dir,
            metrics={"val_mae": None, "val_directional_acc": None},
            version="v_pretrained",
        )
        self.promote_to_production(version)
        return version


def _cli_main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="Kronos NSE model registry")
    parser.add_argument("--checkpoint-dir", default="./checkpoints")
    sub = parser.add_subparsers(dest="cmd", required=True)

    reg = sub.add_parser("register")
    reg.add_argument("--tokenizer", required=True)
    reg.add_argument("--predictor", required=True)
    reg.add_argument("--promote", action="store_true")

    sub.add_parser("bootstrap")

    args = parser.parse_args()
    registry = ModelRegistry(args.checkpoint_dir)

    if args.cmd == "bootstrap":
        version = registry.bootstrap_from_huggingface()
        logger.info("Bootstrapped and promoted: %s", version)
        logger.info("Production paths: %s", registry.get_production_paths())
        return

    metrics_path = Path(args.predictor).parent / "eval_metrics.json"
    metrics: dict[str, Any] = {}
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    version = registry.register_checkpoint(
        tokenizer_path=args.tokenizer,
        predictor_path=args.predictor,
        metrics=metrics,
    )
    logger.info("Registered version: %s", version)
    if args.promote:
        registry.promote_to_production(version)
        logger.info("Promoted %s to production", version)


if __name__ == "__main__":
    _cli_main()
