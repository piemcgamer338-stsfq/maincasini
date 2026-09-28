            UPDATE users
            SET rank_index=$2
            WHERE user_id=$1
            """,
            user_id,
            rank_index,
        )

    async def rank_index(
        self,
        user_id: int,
    ) -> int:

        row = await self.user(user_id)

        return int(
            row["rank_index"]
        )


    async def claim_rank_reward(
        self,
        user_id: int,
        rank_index: int,
        reward=None,
    ) -> bool:
        """Atomically claim a rank reward.

        If reward is supplied, it is credited in the same transaction as the
        claimed-rank marker. The optional third argument preserves compatibility
        with older bot builds that only passed user_id and rank_index.
        """
        reward_value = Decimal(str(reward)) if reward is not None else Decimal("0")

        if rank_index < 0:
            return False
        if reward_value < 0:
            return False

        async with self.pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    SELECT rank_reward_claimed, balance, frozen
                    FROM users
                    WHERE user_id=$1
                    FOR UPDATE
                    """,
                    user_id,
                )

                if not row or row["frozen"]:
                    return False

                claimed = int(row["rank_reward_claimed"] or 0)
                if rank_index <= claimed:
                    return False

                if reward_value > 0:
                    updated = await conn.fetchrow(
                        """
                        UPDATE users
                        SET
                            balance = balance + $2,
                            rank_reward_claimed = $3,
                            updated_at = NOW()
                        WHERE user_id=$1
                        RETURNING balance
                        """,
                        user_id,
                        reward_value,
                        rank_index,
                    )

                    if not updated:
                        return False

                    await conn.execute(
                        """
                        INSERT INTO transactions(
                            user_id, kind, amount, balance_after, note
                        )
                        VALUES($1, 'rank_reward', $2, $3, $4)
                        """,
                        user_id,
                        reward_value,
                        updated["balance"],
                        f"Rank reward #{rank_index}",
                    )
                else:
                    await conn.execute(
                        """
                        UPDATE users
                        SET rank_reward_claimed=$2,
                            updated_at=NOW()
                        WHERE user_id=$1
                        """,
                        user_id,
                        rank_index,
                    )

                return True
