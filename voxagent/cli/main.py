from __future__ import annotations

import asyncio
import shutil
import uuid

import click

from voxagent.config import load_config
from voxagent.db import close_pool, init_pool
from voxagent.knowledge.ingest import crawl_website, ingest_files
from voxagent.knowledge.service import ingest_pages as ingest_pages_service


@click.group()
def cli() -> None:
    """VoxAgent CLI — knowledge ingestion and voice configuration."""


@cli.command()
@click.option("--tenant", required=True, help="Tenant identifier")
@click.option("--url", default=None, help="Website URL to crawl")
@click.option("--depth", default=3, show_default=True, help="Maximum crawl depth")
@click.option("--max-pages", default=100, show_default=True, help="Maximum pages to crawl")
@click.option("--files", multiple=True, help="File paths to ingest (PDF, DOCX, TXT)")
@click.option(
    "--storage-dir",
    default=None,
    help="Directory to store index (default: data/{tenant}/knowledge)",
)
def ingest(
    tenant: str,
    url: str | None,
    depth: int,
    max_pages: int,
    files: tuple[str, ...],
    storage_dir: str | None,
) -> None:
    """Crawl a website and/or ingest files into the knowledge base."""
    if not url and not files:
        raise click.UsageError("Provide --url and/or --files for ingestion.")

    resolved_storage = storage_dir or f"data/{tenant}/knowledge"

    pages = []

    if url:
        click.echo(f"Crawling {url} (depth={depth}, max_pages={max_pages})...")
        crawled = asyncio.run(crawl_website(url, max_depth=depth, max_pages=max_pages))
        click.echo(f"  Crawled {len(crawled)} pages")
        pages.extend(crawled)

    if files:
        click.echo(f"Ingesting {len(files)} file(s)...")
        file_pages = ingest_files(list(files))
        click.echo(f"  Extracted text from {len(file_pages)} file(s)")
        pages.extend(file_pages)

    if not pages:
        click.echo("Nothing to index — all content unchanged.")
        return

    async def _run_ingestion() -> dict[str, object]:
        config = load_config()
        pool = await init_pool(config.database_url)
        try:
            return await ingest_pages_service(pool, tenant_id=uuid.UUID(tenant), pages=pages)
        finally:
            await close_pool(pool)

    click.echo("Building managed index...")
    manifest = asyncio.run(_run_ingestion())
    click.echo(f"Index saved to {resolved_storage}")
    click.echo(f"  Sources tracked: {len(manifest.get('sources', []))}")


@cli.command("voice-setup")
@click.option("--tenant", required=True, help="Tenant identifier")
@click.option("--audio", required=True, type=click.Path(exists=True), help="Reference audio file")
@click.option("--transcript", required=True, help="Transcript of the reference audio")
@click.option(
    "--storage-dir",
    default=None,
    help="Directory to store voice config (default: data/{tenant}/voice)",
)
def voice_setup(
    tenant: str,
    audio: str,
    transcript: str,
    storage_dir: str | None,
) -> None:
    """Set up voice cloning for a tenant from a reference audio sample."""
    import os

    resolved_storage = storage_dir or f"data/{tenant}/voice"
    os.makedirs(resolved_storage, exist_ok=True)

    # Copy audio file to tenant storage
    dest_audio = os.path.join(resolved_storage, "reference_audio" + os.path.splitext(audio)[1])
    shutil.copy2(audio, dest_audio)

    # Save transcript
    transcript_path = os.path.join(resolved_storage, "transcript.txt")
    with open(transcript_path, "w", encoding="utf-8") as f:
        f.write(transcript)

    click.echo(f"Voice clone config saved to {resolved_storage}")
    click.echo(f"  Audio: {dest_audio}")
    click.echo(f"  Transcript: {transcript_path}")
    click.echo(
        f"\nSet these in tenant config:\n"
        f"  clone_audio_path = {dest_audio}\n"
        f"  clone_transcript = {transcript}"
    )
