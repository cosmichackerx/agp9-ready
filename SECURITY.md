# Security

agp9-ready only reads files under the directory you give it and writes a report to stdout or the file you name (and, with `--fix`, rewrites the build files it finds there). It has no network access, no runtime dependencies and executes no project code: it never runs Gradle or a build script.

Found a vulnerability (for example a path traversal through a crafted file name)? Please use GitHub's private vulnerability reporting for this repository ("Security" tab → "Report a vulnerability") instead of a public issue.
