import logging
import os
import shutil
import tempfile
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Optional, Union

from docling.datamodel.base_models import OutputFormat
from docling.datamodel.document import ConversionResult, ConversionStatus, ErrorItem
from docling.utils.profiling import ProfilingItem
from docling_core.types.doc import DoclingDocument, ImageRefMode
from fastapi import BackgroundTasks, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from docling_serve.docling_conversion import ConvertDocumentsOptions

_log = logging.getLogger(__name__)


class DocumentResponse(BaseModel):
    filename: str
    md_content: Optional[str] = None
    json_content: Optional[DoclingDocument] = None
    html_content: Optional[str] = None
    text_content: Optional[str] = None
    doctags_content: Optional[str] = None


class ConvertDocumentResponse(BaseModel):
    document: DocumentResponse
    status: ConversionStatus
    errors: list[ErrorItem] = []
    processing_time: float
    timings: dict[str, ProfilingItem] = {}


class ConvertDocumentErrorResponse(BaseModel):
    status: ConversionStatus


def _export_document_as_content(
    conv_res: ConversionResult,
    export_json: bool,
    export_html: bool,
    export_md: bool,
    export_txt: bool,
    export_doctags: bool,
    image_mode: ImageRefMode,
):

    document = DocumentResponse(filename=conv_res.input.file.name)

    if conv_res.status == ConversionStatus.SUCCESS:
        new_doc = conv_res.document._make_copy_with_refmode(Path(), image_mode)

        # Create the different formats
        if export_json:
            document.json_content = new_doc
        if export_html:
            document.html_content = new_doc.export_to_html(image_mode=image_mode)
        if export_txt:
            document.text_content = new_doc.export_to_markdown(
                strict_text=True, image_mode=image_mode
            )
        if export_md:
            document.md_content = new_doc.export_to_markdown(image_mode=image_mode)
        if export_doctags:
            document.doctags_content = new_doc.export_to_document_tokens()
    elif conv_res.status == ConversionStatus.SKIPPED:
        raise HTTPException(status_code=400, detail=conv_res.errors)
    else:
        raise HTTPException(status_code=500, detail=conv_res.errors)

    return document


def _export_documents_as_files(
    conv_results: Iterable[ConversionResult],
    output_dir: Path,
    export_json: bool,
    export_html: bool,
    export_md: bool,
    export_txt: bool,
    export_doctags: bool,
    image_export_mode: ImageRefMode,
):

    success_count = 0
    failure_count = 0

    for conv_res in conv_results:
        if conv_res.status == ConversionStatus.SUCCESS:
            success_count += 1
            doc_filename = conv_res.input.file.stem

            # Export JSON format:
            if export_json:
                fname = output_dir / f"{doc_filename}.json"
                _log.info(f"writing JSON output to {fname}")
                conv_res.document.save_as_json(
                    filename=fname, image_mode=image_export_mode
                )

            # Export HTML format:
            if export_html:
                fname = output_dir / f"{doc_filename}.html"
                _log.info(f"writing HTML output to {fname}")
                conv_res.document.save_as_html(
                    filename=fname, image_mode=image_export_mode
                )

            # Export Text format:
            if export_txt:
                fname = output_dir / f"{doc_filename}.txt"
                _log.info(f"writing TXT output to {fname}")
                conv_res.document.save_as_markdown(
                    filename=fname,
                    strict_text=True,
                    image_mode=ImageRefMode.PLACEHOLDER,
                )

            # Export Markdown format:
            if export_md:
                fname = output_dir / f"{doc_filename}.md"
                _log.info(f"writing Markdown output to {fname}")
                conv_res.document.save_as_markdown(
                    filename=fname, image_mode=image_export_mode
                )

            # Export Document Tags format:
            if export_doctags:
                fname = output_dir / f"{doc_filename}.doctags"
                _log.info(f"writing Doc Tags output to {fname}")
                conv_res.document.save_as_document_tokens(filename=fname)

        else:
            _log.warning(f"Document {conv_res.input.file} failed to convert.")
            failure_count += 1

    _log.info(
        f"Processed {success_count + failure_count} docs, "
        f"of which {failure_count} failed"
    )


def process_results(
    background_tasks: BackgroundTasks,
    conversion_options: ConvertDocumentsOptions,
    conv_results: Iterable[ConversionResult],
) -> Union[ConvertDocumentResponse, FileResponse]:

    # Let's start by processing the documents
    try:
        start_time = time.monotonic()

        # Convert the iterator to a list to count the number of results and get timings
        # As it's an iterator (lazy evaluation), it will also start the conversion
        conv_results = list(conv_results)

        processing_time = time.monotonic() - start_time

        _log.info(
            f"Processed {len(conv_results)} docs in {processing_time:.2f} seconds."
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    if len(conv_results) == 0:
        raise HTTPException(
            status_code=500, detail="No documents were generated by Docling."
        )

    # We have some results, let's prepare the response
    response: Union[FileResponse, ConvertDocumentResponse]

    # Booleans to know what to export
    export_json = OutputFormat.JSON in conversion_options.to_formats
    export_html = OutputFormat.HTML in conversion_options.to_formats
    export_md = OutputFormat.MARKDOWN in conversion_options.to_formats
    export_txt = OutputFormat.TEXT in conversion_options.to_formats
    export_doctags = OutputFormat.DOCTAGS in conversion_options.to_formats

    # Only 1 document was processed, and we are not returning it as a file
    if len(conv_results) == 1 and not conversion_options.return_as_file:
        conv_res = conv_results[0]
        document = _export_document_as_content(
            conv_res,
            export_json=export_json,
            export_html=export_html,
            export_md=export_md,
            export_txt=export_txt,
            export_doctags=export_doctags,
            image_mode=conversion_options.image_export_mode,
        )

        response = ConvertDocumentResponse(
            document=document,
            status=conv_res.status,
            processing_time=processing_time,
            timings=conv_res.timings,
        )

    # Multiple documents were processed, or we are forced returning as a file
    else:
        # Temporary directory to store the outputs
        work_dir = Path(tempfile.mkdtemp(prefix="docling_"))
        output_dir = work_dir / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        # Worker pid to use in archive identification as we may have multiple workers
        os.getpid()

        # Export the documents
        _export_documents_as_files(
            conv_results=conv_results,
            output_dir=output_dir,
            export_json=export_json,
            export_html=export_html,
            export_md=export_md,
            export_txt=export_txt,
            export_doctags=export_doctags,
            image_export_mode=conversion_options.image_export_mode,
        )

        files = os.listdir(output_dir)

        if len(files) == 0:
            raise HTTPException(status_code=500, detail="No documents were exported.")

        file_path = work_dir / "converted_docs.zip"
        shutil.make_archive(
            base_name=str(file_path.with_suffix("")),
            format="zip",
            root_dir=output_dir,
        )

        # Other cleanups after the response is sent
        # Output directory
        background_tasks.add_task(shutil.rmtree, work_dir, ignore_errors=True)

        response = FileResponse(
            file_path, filename=file_path.name, media_type="application/zip"
        )

    return response
