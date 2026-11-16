"""Kalainova: an agent-driven content studio.

Every stage reads the previous JSON contract in a job folder and writes the next one:

    job.json -> script_packet.json -> asset_manifest.json -> edit_manifest.json
             -> render_plan.json -> out/<job>/final.* -> qa.json -> approval.json
             -> publish_log.json -> measure.json

Media bytes live under the job's work dir (gitignored). JSON lives in the job folder.
"""

__version__ = "0.2.0"

# What every request this engine makes on its own says about itself: the project, never a person.
HTTP_HEADERS = {"User-Agent": "Kalainova/0.1 (https://github.com/kaiverse-io/kalainova)"}
