# Central card setups or trial conversions failing

A customer adds a card or UPI on the Billing page or in the trial Upgrade dialog. Each attempt is a Payment Method. The alert key names the problem.

- `failed:<gateway>`: the gateway saved a card, and Central's check rejected it in the last hour. The alert names the teams and their failure codes.
- `unfinished:<team>`: the team started 2 or more setups in 1 hour and none was saved.
- `conversion-blocked`: an active trial's team has had an active card for 10 minutes, and the trial did not convert.
- `conversion-unmoved`: a converted trial's server still runs a trial plan.

1. For `failed` and `unfinished`, open the Payment Method list in Central and filter by the team. Read **Status**, **Failure Code**, **Decline Code** and **Failure Reason**. A Cancelled setup is one that the team's next attempt replaced.
2. Find the setup in the Stripe or Razorpay dashboard by the team's gateway customer. The gateway shows where the customer stopped, such as 3-D Secure or the bank's e-mandate approval.
3. For `mandate_inactive`, the bank did not keep the e-mandate for an Indian card. Ask the customer to try another card or UPI Autopay.
4. For `conversion-blocked`, open the trial Site and read **Trial Error**. A plan above the team's spending limit stays a trial, and the daily trial job tries again.
5. For `conversion-unmoved`, open the site's server and check its plan and its last resize action. The daily trial job tries the move again.
