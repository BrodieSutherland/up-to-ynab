# Up to YNAB Automatic Transaction Forwarder

If you use YNAB and Up this will help save your life by automatically importing transactions direct from Up into your budget.

## What's all this then

I'm very lazy, and frequently forget to track my transactions manually in my budget, making it kinda useless, and making the job when I eventually get around to it even bigger the more I wait. This machine has saved my life

## Environment Variables

| Variable Name  | Description                                                                                                                                          |
| -------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------- |
| **budgetId**   | This is the budget key in YNAB for your budget, you SHOULD be able to use `last-used`, but I don't recommend (it'll break when you swap budgets)     |
| **PORT**       | Port value to run the app off, just use 5000 (works for me)                                                                                          |
| **upKey**      | Your Up API Personal Access token (grab one [here](https://api.up.com.au/getting_started))                                                           |
| **ynabKey**    | Your YNAB Access token (find it [here](https://app.youneedabudget.com/settings/developer))                                                           |
| **BASE_URL**   | The base URL of wherever you're hosting it, if you're using heroku it will looks something like `https://<YOUR HEROKU APP NAME HERE>.herokuapp.com/` |
| **DEBUG_MODE** | Set this to `False` unless something's gone sideways and you want to investigate it                                                                  |

## Cheers boss, how do I use the thing

First things first, we need to do some prep work. In order to match your Up Accounts with a correlating YNAB Account, we need to have an account in YNAB named "Spending", as well as an account for each Savings account in Up **WITH THE SAME NAME**, emojis and all. For example:

| Up Account Name                | Required YNAB Account Name |
| ------------------------------ | :------------------------: |
| **Main transactional Account** |        **Spending**        |
| **Savings 1**                  |       **Savings 1**        |
| **😀 Savings 2**               |      **😀 Savings 2**      |

To actually use it, there's 3 steps: 1. `git clone https://github.com/BrodieSutherland/up-to-ynab.git` 2. Edit `.env` with the values as shown under "Environment Variables" above 3. `docker-compose up -d`

To reset your databases you can either try hitting your `BASE_URL:PORT` with a GET request, or just restart the service (`docker-compose down && docker-compose up -d`)

<details>
    <summary>Legacy Heroku Deploy Instructions</summary>

    ###I have not tested this/used heroku in a long time, and I cannot confirm this works, use at your own peril!

    Now that's all done, click this fancy lil button down here and deploy your own version of the app!

    [![Deploy](https://www.herokucdn.com/deploy/button.svg)](https://heroku.com/deploy?template=https://github.com/BrodieSutherland/up-to-ynab)

    Once deployed and correctly configured, it will transfer any transactions across to your YNAB budget. If you're unlike me, and have been putting your payees in correctly, then this will associate the payees with those same categories. Any payees it doesnt match will require a category to be "complete".

    To reload the payee to category database, you will need to restart the dynos (I'm looking into making this system better, let me know if you think of something). Personally I recommend letting it run for a month or two, and then resetting the dynos, so you get a good view of your new common payees.

</details>

## FAQ

### Q: Are there any transaction types this doesnt handle?

Glad you asked! Currently it doesn't support split payees, or payees with multiple categories. Also, when a payment value is changed after the initial creation (like when your Uber charge doesn't match the estimate) the initial transaction value will be entered, but not updated.

### I will populate this more, I swear
