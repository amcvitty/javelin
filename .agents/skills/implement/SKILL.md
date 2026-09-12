---
name: implement
description: "Implement a piece of work based on a spec or set of tickets."
disable-model-invocation: true
---

Implement the work described by the user in the spec or tickets.

Create a new branch for the work, called implement/<ticket*number>*<short_description>, where <ticket_number> is the number of the ticket being worked on, and <short_description> is a short description of the work being done. (skip ticket number if not working on a ticket)

If working on tickets, then mark the tickets as "in progress"

Use /tdd where possible, at pre-agreed seams.

Run typechecking regularly, single test files regularly, and the full test suite once at the end.

Once done, use /code-review to review the work.

Commit your work to the current branch and create a PR to the main branch, with a description of the work done and any relevant information for reviewers.

Mark the ticket with the label "ready-for-human" and Status "In Review" when the PR is ready for review.
