FOLDER = "knowledge-base"

# Extension -> content type. The extension decides how a file is read; the content type is only recorded.
ALLOWED_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
}

UPLOADED, PROCESSING, READY, FAILED, DUPLICATE = "uploaded", "processing", "ready", "failed", "duplicate"
IN_PROGRESS = (UPLOADED, PROCESSING)

# A passage is about this long, with a little repeated from the one before so a sentence cut at the edge is not lost.
CHUNK_TOKENS = 400
OVERLAP_TOKENS = 60
EMBED_BATCH = 20
