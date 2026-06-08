# 11 - User Signup, Personal Teams, and Invites

This note explains what Central creates when users sign up and later join each
other's teams.

## Rule

Every enabled User created after Central is installed gets a first team.

Central does this in the `User.after_insert` hook:

1. Add the native `Central User` role.
2. Create one default `Team`.
3. Add the same User as an active `Owner` Team Member.

Permissions still come only from `Team.members`. `Team.owner_user` is metadata
for ownership/billing; it is not a permission bypass.

## Example: John and Jane

John signs up first.

```text
Team: TEAM-00001
team_name: John's Team
owner_user: john@example.com
members:
  - john@example.com | Owner | Active
```

Jane signs up separately.

```text
Team: TEAM-00002
team_name: Jane's Team
owner_user: jane@example.com
members:
  - jane@example.com | Owner | Active
```

John then invites Jane to John's team. After Jane accepts, no new team is needed;
Central adds a Team Member row to John's existing team.

```text
Team: TEAM-00001
team_name: John's Team
owner_user: john@example.com
members:
  - john@example.com | Owner | Active
  - jane@example.com | Developer | Active

Team: TEAM-00002
team_name: Jane's Team
owner_user: jane@example.com
members:
  - jane@example.com | Owner | Active
```

Total teams: 2.

Jane's `fc_teams` claim contains both teams. Her capabilities differ per team:
Owner capabilities in Jane's team, and the invited role's capabilities in John's
team.

If John creates a separate company/team before inviting Jane, then total teams
becomes 3: John's personal team, Jane's personal team, and the company/team.
