# Gap Analysis: superharness vs Paperclip

As of April 5, 2026, the strongest read is: superharness should not try to become Paperclip. It should double down on being the best file-native, verification-first agent protocol, then selectively copy the product ideas that improve dispatch breadth and operator visibility.

The biggest confirmed gaps versus Paperclip are:
- Adapter breadth. Paperclip has a real adapter family and registry shape across Claude, Codex, Cursor, Gemini, OpenClaw, OpenCode, and Pi, while superharness still has a narrower native dispatch surface centered on Claude/Codex plus an OpenClaw module. Sources: [Paperclip README](https://raw.githubusercontent.com/paperclipai/paperclip/master/README.md), [Paperclip adapters](https://github.com/paperclipai/paperclip/tree/master/packages/adapters), [superharness README](/README.md).
- Product UX. Paperclip’s dashboard is a real control plane; superharness’s dashboard is functional but intentionally lightweight. Sources: [Paperclip README](https://raw.githubusercontent.com/paperclipai/paperclip/master/README.md), [superharness GUIDE](/docs/GUIDE.md).
- Plugin formalization. superharness already has a module system, but it is closer to internal lifecycle hooks than a public SDK. Sources: [superharness module plan](/docs/plan-module-system.md), [Paperclip plugin examples](https://github.com/paperclipai/paperclip/tree/master/packages/plugins/examples).
- Packaging/export. Paperclip is selling portability of whole “companies”; superharness has strong state files but not yet a polished export/import story. Sources: [Paperclip README](https://raw.githubusercontent.com/paperclipai/paperclip/master/README.md), [superharness ARCHITECTURE](/docs/ARCHITECTURE.md).

Where superharness should lean in harder:
- Protocol rigor and explicit TDD/verification gates. Sources: [protocol spec](/protocol/spec.md), [superharness GUIDE](/docs/GUIDE.md).
- File-native state, privacy, and portability. Sources: [superharness ARCHITECTURE](/docs/ARCHITECTURE.md), [pyproject.toml](/pyproject.toml).
- Budget and cost controls that already exist but need better operator UX. Sources: [superharness ARCHITECTURE](/docs/ARCHITECTURE.md), [Paperclip README](https://raw.githubusercontent.com/paperclipai/paperclip/master/README.md).
