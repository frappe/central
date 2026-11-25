# Central signups failing or slow

A signup creates a trial site with a Site create Resource Action. The alert key names the problem.

- `failed` (Medium, High at 3): a trial site failed or timed out in the last hour. The alert names the sites and their error codes.
- `waiting:<region>` (Medium, High at 15 minutes): a trial request of the last day has no ready site after 5 minutes.
- `slow:<region>` (Medium): the median time from request to ready site was over 2 minutes for 30 minutes.
- `app-install` (Medium): the product's app did not install on a trial site in the last hour.

1. For `failed`, open the Resource Action list in Central. Filter by Resource Type Site, Action create, and Failed or Timed Out. Read **Error Code** and **Error Message**.
2. For `waiting` and `slow`, check the Atlas of the region and its Beacon alerts. Then check the Central Job Queue and Central Oldest Open Work charts. A stopped worker or a full queue delays every trial.
3. For `app-install`, open the Error Log titled "Trial app install failed". It names the app, the site and the Pilot task. The Site has the same reason in a comment.
