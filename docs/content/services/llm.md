---
title: LLM
description: Turn on AI inference for your team, create an API key, call a model, and control what each key spends.
---

# LLM

LLM gives your team AI inference through an API that is compatible with the OpenAI and the Anthropic SDKs. You call hosted models and models from other providers with one key.

Go to **Services**, then click **LLM**.

<Screenshot name="services/llm" alt="The LLM page. The summary shows the spend of this month, the monthly limit, and the number of live keys. The Usage tab shows cost, requests, and tokens by model." />

::: info
Reading this page needs the **Owner**, **Admin**, **Developer**, **Viewer**, or **Billing** role. Every change needs one of these roles, except **Viewer**. A team with a server on a free trial cannot turn on LLM.
:::

## Turn on LLM

Go to **Services > LLM**. Click **Enable for team**.

## Create an API key

1. Click **Create key**.
2. Type a **Label**, such as `n8n prod`.
3. Select the **Geography**. The geography sets where the requests of the key are served. You cannot change it later.
4. Type the **Cap (USD)**. This is the most that the key can spend in a month, in whole dollars. The minimum is `1`.
5. Click **Create**.

<Clip name="services/llm-create-key" alt="A recording of the LLM page. Create key is clicked, a label is typed, a geography is selected, a cap of 25 dollars is typed, and Create is clicked." />

A dialog shows the **API key**.

::: warning
The console shows the key only one time. Copy it before you close the dialog. If you lose it, revoke the key and create a new one.
:::

A new key can take a few minutes to start working. Your plan sets how many live keys your team can have. The summary shows this number under **Live keys**.

## Call a model

Click **How to call**. The dialog shows the base URL and an example request for each geography.

<Screenshot name="services/llm-how-to-call" alt="The How to call the models dialog. The OpenAI compatible tab shows the base URL of the geography and an example curl request." />

A key works only in its own geography. Use the base URL of that geography.

| SDK | Base URL | Key header |
| --- | --- | --- |
| OpenAI | `<gateway URL>/openai/v1` | `Authorization: Bearer <key>` |
| Anthropic | `<gateway URL>/anthropic` | `x-api-key: <key>` |

Set the model to a **Model key** from the **Models** tab. This example sends a chat request with the OpenAI API:

```bash
curl <gateway URL>/openai/v1/chat/completions \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model": "<model key>", "messages": [{"role": "user", "content": "Hello"}]}'
```

## See the models

Click the **Models** tab. Select a **Geography** to see the models that your keys can call there.

<Screenshot name="services/llm-models" alt="The Models tab. A table lists each model with its provider, model key, input and output types, and the APIs that it supports." />

| Column | Shows |
| --- | --- |
| **Provider** | The company that runs the model. A shield icon means that the provider keeps nothing of your requests. |
| **Model key** | The value to send as `model` in a request. Click it to copy it. |
| **Input** and **Output** | The types of data that the model reads and writes, such as text, images, or audio. |
| **API** | The SDKs that can call the model. |

## Read your usage

The summary shows the cost of this month, the number of requests and tokens, and the cost that the month is on pace for. Click the refresh icon to get new figures. You can refresh 2 times an hour.

The **Usage** tab shows **Cost**, **Requests**, and **Tokens** for each day, and a table for each model. Select a key or a period to change what it shows. The periods are **Last 7 days**, **Last 30 days**, **This month**, and **Last month**. Days are in UTC.

## Control spend

Each key has a cap. A key that reaches its cap is refused until the next month or until you raise the cap.

Your plan has a **Monthly limit**. The caps of all live keys and the spend of this month must fit in this limit.

<Screenshot name="services/llm-keys" alt="The API keys tab. A table lists three keys with their geography, creation date, and spend of this month against the cap of each key." />

To change the caps:

1. Click the **API keys** tab. Click **Set caps**.
2. Type a new **Cap (USD)** for each key that you want to change.
3. Click **Save caps**.

The console saves all caps together. If the total passes your monthly limit, the console saves none.

Your team pays for its usage at the end of the month. If an invoice is unpaid, the **API keys** tab shows **Keys are paused** and every key is refused until you pay.

## Revoke a key

You cannot undo this.

1. Click the **API keys** tab.
2. Click the actions menu on the key. Click **Revoke**.
3. Click **Revoke** to confirm.

Apps that use the key stop working in a few minutes. The cap of the key becomes free for another key.

## Log prompts and outputs

Click the **Settings** tab. Turn on **Log prompts and outputs** to keep the prompts and the model replies. Support can then look into a failed request. This is off until you turn it on.

## If LLM is under maintenance

The page shows **LLM service is under maintenance** when it cannot reach the service. Your API keys keep working. You cannot see or change usage, keys, and caps until the service is back.

## See also

- [Object Storage](/services/object-storage)
- [Roles and permissions](/team/roles)
- [Credits and spend limits](/billing/limits)
- [Invoices](/billing/invoices)
