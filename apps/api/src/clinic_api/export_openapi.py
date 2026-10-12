"""Print the OpenAPI schema; @clinic/api-client generates TypeScript types from it."""

import json
import sys

from clinic_api.main import app

if __name__ == "__main__":
    out = sys.argv[1] if len(sys.argv) > 1 else None
    schema = json.dumps(app.openapi(), indent=2)
    if out:
        with open(out, "w") as f:
            f.write(schema)
    else:
        print(schema)
