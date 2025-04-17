from loguru import logger

async def m001_initial(db):
    """
    Initial database migration for the Taproot Assets extension.
    """
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS taproot_assets.settings (
            id TEXT PRIMARY KEY,
            tapd_host TEXT NOT NULL,
            tapd_network TEXT NOT NULL,
            tapd_tls_cert_path TEXT NOT NULL,
            tapd_macaroon_path TEXT NOT NULL,
            tapd_macaroon_hex TEXT,
            lnd_macaroon_path TEXT NOT NULL,
            lnd_macaroon_hex TEXT,
            default_sat_fee INTEGER NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS taproot_assets.assets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            type TEXT NOT NULL,
            amount TEXT NOT NULL,
            genesis_point TEXT NOT NULL,
            meta_hash TEXT NOT NULL,
            version TEXT NOT NULL,
            is_spent BOOLEAN NOT NULL DEFAULT FALSE,
            script_key TEXT NOT NULL,
            channel_info TEXT, -- JSON encoded channel info
            user_id TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS taproot_assets.invoices (
            id TEXT PRIMARY KEY,
            payment_hash TEXT NOT NULL,
            payment_request TEXT NOT NULL,
            asset_id TEXT NOT NULL,
            asset_amount INTEGER NOT NULL,
            satoshi_amount INTEGER NOT NULL DEFAULT 1,
            memo TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            user_id TEXT NOT NULL,
            wallet_id TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            expires_at TIMESTAMP,
            paid_at TIMESTAMP
        );
        """
    )


async def m002_add_sat_fee_column(db):
    """
    Migration to add default_sat_fee column to settings table if it doesn't exist.
    """
    try:
        # Check if the column exists
        columns = await db.fetchall(
            "SELECT name FROM pragma_table_info('taproot_assets.settings')"
        )
        column_names = [col["name"] for col in columns]

        # Add column if it doesn't exist
        if "default_sat_fee" not in column_names:
            await db.execute(
                """
                ALTER TABLE taproot_assets.settings
                ADD COLUMN default_sat_fee INTEGER NOT NULL DEFAULT 1;
                """
            )
            logger.info("Added default_sat_fee column to taproot_assets.settings table")
        else:
            logger.debug("default_sat_fee column already exists in settings table")
    except Exception as e:
        logger.warning(f"Error in migration m002_add_sat_fee_column: {str(e)}")


async def m003_create_fee_transactions_table(db):
    """
    Migration to create a table for tracking sat fee transactions.
    """
    try:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS taproot_assets.fee_transactions (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                wallet_id TEXT NOT NULL,
                asset_payment_hash TEXT NOT NULL,
                fee_amount_msat INTEGER NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        logger.info("Created taproot_assets.fee_transactions table")
    except Exception as e:
        logger.warning(f"Error in migration m003_create_fee_transactions_table: {str(e)}")


async def m004_create_payments_table(db):
    """
    Migration to create a table for tracking sent payments of Taproot Assets.
    """
    try:
        # Create the payments table with indices
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS taproot_assets.payments (
                id TEXT PRIMARY KEY,
                payment_hash TEXT NOT NULL,
                payment_request TEXT NOT NULL,
                asset_id TEXT NOT NULL,
                asset_amount INTEGER NOT NULL,
                fee_sats INTEGER NOT NULL DEFAULT 0,
                memo TEXT,
                status TEXT NOT NULL DEFAULT 'completed',
                user_id TEXT NOT NULL,
                wallet_id TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                preimage TEXT
            );
            """
        )
        
        # Add index on payment_hash for faster lookups
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS payments_payment_hash_idx 
            ON taproot_assets.payments (payment_hash);
            """
        )
        
        # Add index on user_id for faster user-specific queries
        await db.execute(
            """
            CREATE INDEX IF NOT EXISTS payments_user_id_idx 
            ON taproot_assets.payments (user_id);
            """
        )
        
        logger.info("Created taproot_assets.payments table with indices")
    except Exception as e:
        # Log just the error message without a full stack trace for migrations
        logger.warning(f"Error in migration m004_create_payments_table: {str(e)}")
