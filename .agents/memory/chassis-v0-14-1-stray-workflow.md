---
name: chassis-v0-14-1-stray-workflow
description: chassis v0.14.1 emits .github/workflows/.yaml with release automation off
---
The conditional filename renders empty, leaving a live release-please workflow named `.yaml`. It was left out of this repo (ADR 0008). Delete it if `copier update` restores it, until fixed upstream.
