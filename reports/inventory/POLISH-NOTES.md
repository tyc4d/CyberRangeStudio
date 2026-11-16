# Inventory — polish items for QA (not blockers)
- A catalogue-resolvable service with no stated version (e.g. nginx) emits TWO version missing_items:
  "version for nginx" (status=open, question=None) AND "deployed version of nginx" (status=substitute_chosen,
  discloses the catalogue version). Neither blocks the user (question=None), but the open-no-question item is a
  mild UX wart — ideally dedup to one resolved disclosure. Owner-visible on the deps/missing UI.
