# Jobs

One directory per piece. Copy `_template` to a new id. Write the subject only inside that directory.

```
jobs/<id>/
  job.json            required
  script_packet.json  when there is a script
  asset_manifest.json when there are files on disk
  edit_manifest.json  when something is being cut or mixed
  render_plan.json    only after a compiler exists
  measure.json        after publish
```

Do not put a sample subject in `_template`. Do not commit media.
