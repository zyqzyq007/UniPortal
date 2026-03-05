-- CreateTable
CREATE TABLE "User" (
    "id" TEXT NOT NULL PRIMARY KEY,
    "username" TEXT NOT NULL,
    "password" TEXT NOT NULL,
    "last_login" DATETIME,
    "created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CreateTable
CREATE TABLE "test_projects" (
    "project_id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "description" TEXT,
    "path" TEXT,
    "created_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "item_count" INTEGER NOT NULL DEFAULT 0,
    "last_upload_at" DATETIME,
    "owner_id" TEXT NOT NULL,
    CONSTRAINT "test_projects_owner_id_fkey" FOREIGN KEY ("owner_id") REFERENCES "User" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "software_items" (
    "item_id" TEXT NOT NULL PRIMARY KEY,
    "name" TEXT NOT NULL,
    "version" TEXT,
    "file_path" TEXT NOT NULL,
    "file_size" BIGINT NOT NULL,
    "uploaded_at" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "project_id" TEXT NOT NULL,
    "created_by" TEXT NOT NULL,
    CONSTRAINT "software_items_project_id_fkey" FOREIGN KEY ("project_id") REFERENCES "test_projects" ("project_id") ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT "software_items_created_by_fkey" FOREIGN KEY ("created_by") REFERENCES "User" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateIndex
CREATE UNIQUE INDEX "User_username_key" ON "User"("username");

-- CreateIndex
CREATE INDEX "software_items_project_id_idx" ON "software_items"("project_id");

-- CreateIndex
CREATE INDEX "software_items_name_idx" ON "software_items"("name");

-- CreateIndex
CREATE INDEX "software_items_uploaded_at_idx" ON "software_items"("uploaded_at" DESC);
