# Car Vault (Car Scout) - Setup Guide

This guide will help you run the project in VS Code and connect it to a PostgreSQL database.

## Prerequisites

1.  **Node.js**: Ensure Node.js is installed. (Run `node -v` to check)
2.  **PostgreSQL**: Download and install PostgreSQL from [postgresql.org](https://www.postgresql.org/download/).
3.  **VS Code**: Recommended editor.

---

## Part 1: Running the Project in VS Code

### 1. Open the Project
- Open VS Code.
- Go to `File` > `Open Folder` and select the `Car Vault (Car scout)` folder.

### 2. Install Dependencies
You need to install libraries for both the Server (Backend) and Client (Frontend).

**Open a Terminal in VS Code** (`Ctrl + ~` or `Terminal > New Terminal`):

**For Server:**
```bash
cd server
npm install
```

**For Client (open a new terminal split or tab):**
```bash
cd client
npm install
```

### 3. Start the Application

**Start Backend (Server):**
In the server terminal:
```bash
npm start
```
*Expected Output:* `Server running on port 5000`

**Start Frontend (Client):**
In the client terminal:
```bash
npm run dev
```
*Expected Output:* `Local: http://localhost:5173/`

**View the App:**
Open your browser and go to `http://localhost:5173`.

---

## Part 2: Connecting to PostgreSQL

### 1. Install & Setup PostgreSQL
If you haven't installed PostgreSQL yet, download and install it. During installation, remember the **password** you set for the `postgres` user.

### 2. Create the Database
Open **pgAdmin** (comes with PostgreSQL) or use the command line (SQL Shell).

**Using SQL Shell (psql):**
1.  Open "SQL Shell (psql)".
2.  Press Enter for default defaults (Server, Database, Port, Username).
3.  Enter your password when prompted.
4.  Run the following command to create the database:
    ```sql
    CREATE DATABASE car_vault;
    ```

### 3. Run the Schema (Create Tables)
Copy the contents of `docs/schema.sql` and run them in your SQL tool (pgAdmin Query Tool or psql) to create the necessary tables.

### 4. Configure the Application
1.  Open `server/.env` file in VS Code.
2.  Update the `DATABASE_URL` line with your actual password:

    ```env
    DATABASE_URL=postgres://postgres:YOUR_PASSWORD_HERE@localhost:5432/car_vault
    ```
    *Replace `YOUR_PASSWORD_HERE` with the password you set during installation.*

### 5. Verify Connection
Restart the server (`Ctrl + C` to stop, then `npm start` again).
If connected successfully, you will see:
`Database connected: [Current Timestamp]`

---

## Troubleshooting

-   **Error: "Connection refused"**: Make sure PostgreSQL service is running.
-   **Error: "password authentication failed"**: Check your password in the `.env` file.
-   **Mock Mode**: If the database is not connected, the server automatically switches to "Mock Mode" so you can still use the app with sample data.
