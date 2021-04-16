# Up to YNAB Automatic Transaction Forwarder
If you use YNAB and Up this will help save your life by automatically importing transactions direct from Up into your budget.

## What's all this then
I'm very lazy, and frequently forget to track my transactions manually in my budget, making it kinda useless, and making the job when I eventually get around to it even bigger the more I wait. This machine has saved my life

## Environment Variables

| Variable Name | Description 
|---------------|:-----------:
|**budgetId**   | This is the budget key in YNAB for your budget, you SHOULD be able to use `last-used`, but I don't recommend (it'll break when you swap budgets)
|**PORT**       |Port value to run the app off, just use 5000 (works for me)
|**upKey**      |Your Up API Personal Access token (grab one [here](https://api.up.com.au/getting_started))
|**ynabKey**    |Your YNAB Access token (find it [here](https://app.youneedabudget.com/settings/developer))
|**HEROKU_BASE_URL**|The base URL of your Heroku App, I used the [dyno metadata](https://devcenter.heroku.com/articles/dyno-metadata) to get this variable (and a bunch of others) automatically

## Cheers boss, how do I use the thing
Click this fancy lil button down here and deploy your own version of the app! 

[![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/BrodieSutherland/up-to-ynab)

## FAQ
### I will populate this I swear 