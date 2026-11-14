---
title: Object Storage
description: Create a bucket, connect an S3 client, manage files, set a quota, and rotate the key.
---

# Object Storage

Object Storage keeps files in buckets that any S3 client can read and write. Each bucket lives in one region and has one access key that opens only that bucket.

Go to **Services**, then click **Object Storage**.

<Screenshot name="services/object-storage" alt="The Object Storage page. A summary shows 173 GB in 19,987 objects and a bar with the share of each bucket. Below it are cards for three buckets in Mumbai." />

::: info
Reading buckets needs the **Owner**, **Admin**, **Developer**, **Viewer**, or **Billing** role. Every change on this page needs one of these roles, except **Viewer**. A team with a server on a free trial cannot create a bucket.
:::

## Create a bucket

1. Go to **Services > Object Storage**. Click **Create bucket**.
2. Type a **Name**. Use lowercase letters, digits, dots, and hyphens. End the name with a letter or a digit.
3. Select the **Region**. Objects stay in this region. You cannot move a bucket to another region later.
4. Click **Create bucket**.

<Screenshot name="services/create-bucket" alt="The Create bucket dialog with a map of the region, the name media, and the region Mumbai, India." />

The console adds the number of your team and the region to the name. A bucket that you name `media` gets a full name such as `52-bom-media`. Use the full name in your S3 client.

The **Save your credentials** dialog opens. It shows the **Endpoint URL**, the **Bucket**, the **Access key**, and the **Secret key**.

::: warning
The console shows the secret key only in this dialog. Copy it before you click **Done**. If you lose it, [rotate the key](#rotate-the-key) to get a new one.
:::

Click **Copy as .env** to copy all four values as environment variables.

## Connect an S3 client

Use the values from the **Save your credentials** dialog. The **Settings** tab of the bucket shows the endpoint, the bucket name, and the access key again, under **Connection**. Set your client to path-style addressing and signature version 4.

This example lists a bucket with the AWS command line client:

```bash
export AWS_ACCESS_KEY_ID=<access key>
export AWS_SECRET_ACCESS_KEY=<secret key>
aws s3 ls s3://52-bom-media --endpoint-url <endpoint URL>
```

To send the backups of a site to the bucket, type the same values in Pilot. Read [Keep a copy offsite](/pilot/backups#keep-a-copy-offsite).

## Manage files

Click a bucket. The **Files** tab lists its folders and files, 20 on a page.

<Screenshot name="services/bucket-files" alt="The Files tab of the media bucket. A table lists two folders and four files with their size and the time of the last change." />

| To | Do this |
| --- | --- |
| Open a folder | Click its name. Click **All files** to go back to the top. |
| Find a file | Type the start of its name in **Search by name**. |
| Upload files | Click **Upload** and select the files. A file with the same name replaces the old one. |
| Download a file | Click the download icon on its row. |
| Delete files or folders | Select the rows. Click **Delete**, then **Delete** again to confirm. |

::: warning
A deleted folder loses everything inside it. You cannot undo a delete.
:::

The console uploads files of up to 5 GB. Use an S3 client for a larger file. You can delete at most 1000 objects at one time.

## Set a quota

A quota stops a bucket from growing past a limit. A bucket without a quota grows as you upload.

1. Click the bucket. Click the **Settings** tab.
2. Under **Quota**, click **Set quota**.
3. Type the **Size limit (GiB)**, the **Object limit**, or both. `0` means no limit.
4. Click **Save quota**.

<Screenshot name="services/bucket-settings" alt="The Settings tab of the media bucket with the Quota section, the Connection section with the endpoint, bucket, and access key, and the Delete bucket section." />

The bucket refuses an upload that passes a limit.

## Rotate the key

1. Click the bucket. Click the **Settings** tab.
2. Under **Connection**, click **Rotate key**.
3. Click **Rotate key** to confirm.
4. Copy the new values from the **Save your credentials** dialog.

Everything that uses the old key stops working at once. Update each client with the new key.

## Delete a bucket

You can delete only an empty bucket. This deletes the bucket and its access key. You cannot undo this.

1. Delete all objects in the **Files** tab.
2. Click the **Settings** tab. Under **Delete bucket**, click **Delete bucket**.
3. Type the name of the bucket. Click **Delete bucket**.

## Cost

Your team pays one Object Storage plan for each region that holds a bucket. All buckets in the region share the storage that the plan includes. The plan stops when you delete the last bucket in the region.

When the region has a price, the **Create bucket** dialog shows the included storage and the price for a month. Read [How billing works](/billing/) for the invoice.

## See also

- [Backups and restore](/pilot/backups)
- [Regions](/servers/regions)
- [Roles and permissions](/team/roles)
- [How billing works](/billing/)
