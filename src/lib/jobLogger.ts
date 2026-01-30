import { getSupabaseAdmin } from "./supabaseAdmin";

export interface JobRunSummary {
  churchesProcessed?: number;
  emailsSent?: number;
  emailsFailed?: number;
  donationsProcessed?: number;
  receiptsSent?: number;
  receiptsFailed?: number;
  [key: string]: any; // Allow additional fields
}

/**
 * Log a job run to the job_runs table
 */
export async function logJobRun(
  jobName: string,
  status: "success" | "error",
  summary?: JobRunSummary,
  error?: string
): Promise<void> {
  try {
    const supabase = getSupabaseAdmin();

    const { error: insertError } = await supabase.from("job_runs").insert({
      job_name: jobName,
      finished_at: new Date().toISOString(),
      status,
      summary: summary || null,
      error: error || null,
    });

    if (insertError) {
      console.error(`[Job Logger] Failed to log job run for ${jobName}`, {
        error: insertError.message,
      });
      // Don't throw - logging failure shouldn't break the job
    }
  } catch (err: any) {
    console.error(`[Job Logger] Unexpected error logging job run for ${jobName}`, err);
    // Don't throw - logging failure shouldn't break the job
  }
}

/**
 * Start a job run and return the run ID
 * Call this at the start of a job, then call logJobRun with the same jobName at the end
 */
export async function startJobRun(jobName: string): Promise<string | null> {
  try {
    const supabase = getSupabaseAdmin();

    const { data, error: insertError } = await supabase
      .from("job_runs")
      .insert({
        job_name: jobName,
        status: "success", // Will be updated when finished
        finished_at: null,
      })
      .select("id")
      .single();

    if (insertError) {
      console.error(`[Job Logger] Failed to start job run for ${jobName}`, {
        error: insertError.message,
      });
      return null;
    }

    return data.id;
  } catch (err: any) {
    console.error(`[Job Logger] Unexpected error starting job run for ${jobName}`, err);
    return null;
  }
}
