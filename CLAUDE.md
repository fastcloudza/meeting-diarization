# CLAUDE.md


Git rule: never create or use git worktrees in this repo. Work on a branch in the main checkout. Merge to main locally, then push origin main. Never push HEAD:main from a branch. After a branch is merged and main is pushed, delete the local branch.
