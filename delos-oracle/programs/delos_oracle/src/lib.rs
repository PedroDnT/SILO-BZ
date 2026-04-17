use anchor_lang::prelude::*;

declare_id!("DeLoSXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX");

/// Delos Oracle — BCB macroeconomic data on Solana
///
/// All rate values are stored as integers scaled to avoid floating point:
///   - Interest/inflation rates: basis-point integers (multiply % by 100)
///       e.g. 10.75% SELIC → selic_meta = 1075
///   - FX rates: scaled × 10,000 (4 decimal precision)
///       e.g. USD/BRL 5.1234 → usdbrl = 51234
///
/// PDA derivation:
///   seeds = ["macro_state", authority_pubkey]
#[program]
pub mod delos_oracle {
    use super::*;

    /// Initialise the MacroState PDA.
    /// Must be called once by the oracle authority before any updates.
    pub fn initialize(ctx: Context<Initialize>) -> Result<()> {
        let state = &mut ctx.accounts.macro_state;
        state.authority    = ctx.accounts.authority.key();
        state.selic_meta   = 0;
        state.selic_diaria = 0;
        state.cdi          = 0;
        state.ipca         = 0;
        state.igpm         = 0;
        state.usdbrl       = 0;
        state.updated_ts   = 0;
        state.slot         = 0;
        state.bump         = ctx.bumps.macro_state;
        msg!("Delos Oracle initialised by {}", state.authority);
        Ok(())
    }

    /// Post updated BCB macroeconomic values on-chain.
    ///
    /// Only callable by the authority that initialised this PDA.
    /// All values are pre-scaled integers from the off-chain relayer.
    pub fn update_macro_state(
        ctx: Context<UpdateMacroState>,
        selic_meta:   i64,
        selic_diaria: i64,
        cdi:          i64,
        ipca:         i64,
        igpm:         i64,
        usdbrl:       i64,
        updated_ts:   i64,
    ) -> Result<()> {
        let state = &mut ctx.accounts.macro_state;

        state.selic_meta   = selic_meta;
        state.selic_diaria = selic_diaria;
        state.cdi          = cdi;
        state.ipca         = ipca;
        state.igpm         = igpm;
        state.usdbrl       = usdbrl;
        state.updated_ts   = updated_ts;
        state.slot         = Clock::get()?.slot;

        emit!(MacroStateUpdated {
            authority:    state.authority,
            selic_meta,
            ipca,
            usdbrl,
            updated_ts,
            slot:         state.slot,
        });

        msg!(
            "MacroState updated — SELIC={} IPCA={} USDBRL={} ts={}",
            selic_meta, ipca, usdbrl, updated_ts
        );
        Ok(())
    }
}

// =============================================================================
// Accounts
// =============================================================================

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(mut)]
    pub authority: Signer<'info>,

    #[account(
        init,
        payer = authority,
        space = 8 + MacroState::INIT_SPACE,
        seeds = [b"macro_state", authority.key().as_ref()],
        bump
    )]
    pub macro_state: Account<'info, MacroState>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct UpdateMacroState<'info> {
    pub authority: Signer<'info>,

    #[account(
        mut,
        seeds = [b"macro_state", authority.key().as_ref()],
        bump = macro_state.bump,
        constraint = macro_state.authority == authority.key() @ OracleError::Unauthorized
    )]
    pub macro_state: Account<'info, MacroState>,
}

// =============================================================================
// State
// =============================================================================

/// On-chain macroeconomic state — 114 bytes + 8 discriminator = 122 bytes total.
/// Fits in a single account, well within Solana's account size limits.
#[account]
#[derive(InitSpace)]
pub struct MacroState {
    /// Authority that may post updates (32 bytes)
    pub authority: Pubkey,

    /// SELIC meta (target) rate in basis points × 100
    /// e.g. 10.75% → 1075
    pub selic_meta: i64,

    /// SELIC overnight (diária) in basis points × 100
    pub selic_diaria: i64,

    /// CDI rate in basis points × 100
    pub cdi: i64,

    /// IPCA 12-month accumulated inflation in basis points × 100
    pub ipca: i64,

    /// IGP-M 12-month accumulated inflation in basis points × 100
    pub igpm: i64,

    /// USD/BRL exchange rate scaled × 10_000
    /// e.g. 5.1234 → 51234
    pub usdbrl: i64,

    /// Unix timestamp (seconds) of the BCB data point being posted
    pub updated_ts: i64,

    /// Solana slot at the time of the last update transaction
    pub slot: u64,

    /// PDA bump seed (1 byte)
    pub bump: u8,
}

// =============================================================================
// Events
// =============================================================================

#[event]
pub struct MacroStateUpdated {
    pub authority:  Pubkey,
    pub selic_meta: i64,
    pub ipca:       i64,
    pub usdbrl:     i64,
    pub updated_ts: i64,
    pub slot:       u64,
}

// =============================================================================
// Errors
// =============================================================================

#[error_code]
pub enum OracleError {
    #[msg("Caller is not the oracle authority for this PDA")]
    Unauthorized,
}
