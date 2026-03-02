import { StatusBar } from "expo-status-bar";
import { useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  Linking,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

const TABS = ["Dashboard", "Checklist", "Documents", "Communications"];

const initialCommunicationForm = {
  transactionId: "",
  communicationType: "phone_call",
  contactParty: "agent",
  contactName: "",
  summary: "",
  outcome: "",
  followUpDate: "",
};

export default function App() {
  const [apiBaseUrl, setApiBaseUrl] = useState("https://maverick-tc.up.railway.app");
  const [username, setUsername] = useState("margaret");
  const [password, setPassword] = useState("");
  const [token, setToken] = useState("");
  const [activeTab, setActiveTab] = useState("Dashboard");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const [dashboardData, setDashboardData] = useState(null);
  const [checklistData, setChecklistData] = useState(null);
  const [documentTransactionId, setDocumentTransactionId] = useState("");
  const [documentsPayload, setDocumentsPayload] = useState(null);
  const [communicationForm, setCommunicationForm] = useState(initialCommunicationForm);
  const [communications, setCommunications] = useState([]);

  const normalizedBaseUrl = useMemo(() => apiBaseUrl.trim().replace(/\/+$/, ""), [apiBaseUrl]);

  const apiRequest = async (path, options = {}, authTokenOverride = null) => {
    const url = `${normalizedBaseUrl}${path}`;
    const tokenToUse = authTokenOverride ?? token;
    const headers = {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(tokenToUse ? { Authorization: `Bearer ${tokenToUse}` } : {}),
      ...(options.headers || {}),
    };
    const response = await fetch(url, {
      method: options.method || "GET",
      headers,
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok || body.success === false) {
      throw new Error(body.error || `Request failed (${response.status})`);
    }
    return body;
  };

  const login = async () => {
    setBusy(true);
    setError("");
    try {
      const response = await apiRequest(
        "/api/mobile/login",
        {
          method: "POST",
          body: { username: username.trim(), password },
        },
        ""
      );
      setToken(response.access_token || "");
      setActiveTab("Dashboard");
      setPassword("");
    } catch (requestError) {
      setError(requestError.message || "Unable to sign in");
    } finally {
      setBusy(false);
    }
  };

  const loadDashboard = async () => {
    setBusy(true);
    setError("");
    try {
      const response = await apiRequest("/api/mobile/dashboard");
      setDashboardData(response);
    } catch (requestError) {
      setError(requestError.message || "Unable to load dashboard");
    } finally {
      setBusy(false);
    }
  };

  const loadChecklist = async () => {
    setBusy(true);
    setError("");
    try {
      const response = await apiRequest("/api/mobile/daily-checklist");
      setChecklistData(response);
    } catch (requestError) {
      setError(requestError.message || "Unable to load checklist");
    } finally {
      setBusy(false);
    }
  };

  const loadDocuments = async () => {
    const id = (documentTransactionId || "").trim();
    if (!id) {
      setError("Enter a transaction ID first");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await apiRequest(`/api/mobile/transaction/${id}/documents`);
      setDocumentsPayload(response);
    } catch (requestError) {
      setError(requestError.message || "Unable to load documents");
    } finally {
      setBusy(false);
    }
  };

  const loadCommunications = async () => {
    const id = (communicationForm.transactionId || "").trim();
    if (!id) {
      setError("Enter a transaction ID first");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const response = await apiRequest(`/api/mobile/transaction/${id}/communications`);
      setCommunications(response.communications || []);
    } catch (requestError) {
      setError(requestError.message || "Unable to load communications");
    } finally {
      setBusy(false);
    }
  };

  const submitCommunication = async () => {
    const id = (communicationForm.transactionId || "").trim();
    if (!id) {
      setError("Transaction ID is required for communication log");
      return;
    }
    if (!communicationForm.summary.trim()) {
      setError("Summary is required");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await apiRequest(`/api/mobile/transaction/${id}/communications`, {
        method: "POST",
        body: {
          communication_type: communicationForm.communicationType,
          contact_party: communicationForm.contactParty,
          contact_name: communicationForm.contactName.trim(),
          summary: communicationForm.summary.trim(),
          outcome: communicationForm.outcome.trim(),
          follow_up_date: communicationForm.followUpDate.trim() || null,
        },
      });
      Alert.alert("Saved", "Communication logged.");
      setCommunicationForm((prev) => ({
        ...prev,
        contactName: "",
        summary: "",
        outcome: "",
        followUpDate: "",
      }));
      await loadCommunications();
    } catch (requestError) {
      setError(requestError.message || "Unable to log communication");
    } finally {
      setBusy(false);
    }
  };

  const markTaskComplete = async (taskId) => {
    setBusy(true);
    setError("");
    try {
      await apiRequest(`/api/mobile/task/${taskId}/complete`, {
        method: "POST",
        body: { completed: true },
      });
      await loadChecklist();
    } catch (requestError) {
      setError(requestError.message || "Unable to complete task");
    } finally {
      setBusy(false);
    }
  };

  const markCallComplete = async (deadlineId) => {
    setBusy(true);
    setError("");
    try {
      await apiRequest(`/api/mobile/call/${deadlineId}/complete`, {
        method: "POST",
        body: { made: true },
      });
      await loadChecklist();
    } catch (requestError) {
      setError(requestError.message || "Unable to update call");
    } finally {
      setBusy(false);
    }
  };

  const openPhone = async (phoneLink) => {
    if (!phoneLink) {
      Alert.alert("No phone", "No call number available for this item.");
      return;
    }
    try {
      await Linking.openURL(phoneLink);
    } catch {
      Alert.alert("Call failed", "Unable to open dialer.");
    }
  };

  const openExternalUrl = async (url) => {
    if (!url) {
      Alert.alert("Missing link", "No URL available for this document.");
      return;
    }
    try {
      await Linking.openURL(url);
    } catch {
      Alert.alert("Open failed", "Unable to open this document URL.");
    }
  };

  useEffect(() => {
    if (!token) {
      return;
    }
    if (activeTab === "Dashboard" && !dashboardData) {
      loadDashboard();
      return;
    }
    if (activeTab === "Checklist" && !checklistData) {
      loadChecklist();
    }
  }, [activeTab, token]);

  const logout = () => {
    setToken("");
    setDashboardData(null);
    setChecklistData(null);
    setDocumentsPayload(null);
    setCommunications([]);
    setError("");
  };

  if (!token) {
    return (
      <SafeAreaView style={styles.container}>
        <StatusBar style="dark" />
        <ScrollView contentContainerStyle={styles.content}>
          <Text style={styles.title}>Maverick Mobile</Text>
          <Text style={styles.subtitle}>Sign in with TC credentials</Text>

          <Text style={styles.label}>API Base URL</Text>
          <TextInput style={styles.input} value={apiBaseUrl} onChangeText={setApiBaseUrl} autoCapitalize="none" />

          <Text style={styles.label}>Username</Text>
          <TextInput style={styles.input} value={username} onChangeText={setUsername} autoCapitalize="none" />

          <Text style={styles.label}>Password</Text>
          <TextInput
            style={styles.input}
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            autoCapitalize="none"
          />

          <Pressable style={styles.button} onPress={login} disabled={busy}>
            <Text style={styles.buttonText}>{busy ? "Signing in..." : "Sign In"}</Text>
          </Pressable>

          {error ? <Text style={styles.errorText}>{error}</Text> : null}
        </ScrollView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <StatusBar style="dark" />
      <View style={styles.topBar}>
        <Text style={styles.titleSmall}>Maverick Mobile</Text>
        <Pressable onPress={logout}>
          <Text style={styles.linkText}>Logout</Text>
        </Pressable>
      </View>

      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.tabBar}>
        {TABS.map((tab) => (
          <Pressable
            key={tab}
            onPress={() => setActiveTab(tab)}
            style={[styles.tabButton, activeTab === tab && styles.tabButtonActive]}
          >
            <Text style={[styles.tabButtonText, activeTab === tab && styles.tabButtonTextActive]}>{tab}</Text>
          </Pressable>
        ))}
      </ScrollView>

      {busy ? <ActivityIndicator style={styles.loader} size="small" color="#2563eb" /> : null}
      {error ? <Text style={styles.errorText}>{error}</Text> : null}

      <ScrollView contentContainerStyle={styles.content}>
        {activeTab === "Dashboard" ? (
          <DashboardTab dashboardData={dashboardData} onRefresh={loadDashboard} />
        ) : null}

        {activeTab === "Checklist" ? (
          <ChecklistTab
            checklistData={checklistData}
            onRefresh={loadChecklist}
            onTaskComplete={markTaskComplete}
            onCallComplete={markCallComplete}
            onOpenPhone={openPhone}
          />
        ) : null}

        {activeTab === "Documents" ? (
          <DocumentsTab
            transactionId={documentTransactionId}
            setTransactionId={setDocumentTransactionId}
            documentsPayload={documentsPayload}
            onRefresh={loadDocuments}
            onOpenUrl={openExternalUrl}
          />
        ) : null}

        {activeTab === "Communications" ? (
          <CommunicationsTab
            form={communicationForm}
            setForm={setCommunicationForm}
            communications={communications}
            onSubmit={submitCommunication}
            onLoad={loadCommunications}
          />
        ) : null}
      </ScrollView>
    </SafeAreaView>
  );
}

function DashboardTab({ dashboardData, onRefresh }) {
  const summary = dashboardData?.summary || {};
  const needsReview = dashboardData?.needs_review || [];
  const active = dashboardData?.active_transactions || [];

  return (
    <View>
      <Pressable style={styles.buttonSecondary} onPress={onRefresh}>
        <Text style={styles.buttonSecondaryText}>Refresh Dashboard</Text>
      </Pressable>

      <View style={styles.kpiRow}>
        <KpiCard label="Needs Review" value={summary.needs_review_count || 0} />
        <KpiCard label="Active" value={summary.active_count || 0} />
      </View>

      <Text style={styles.sectionTitle}>Needs Review</Text>
      {needsReview.length === 0 ? <Text style={styles.mutedText}>No transactions waiting.</Text> : null}
      {needsReview.map((item) => (
        <View key={`review-${item.id}`} style={styles.card}>
          <Text style={styles.cardTitle}>{item.property_address || "No address"}</Text>
          <Text style={styles.cardText}>
            {item.agent_name} • {item.agent_phone}
          </Text>
          <Text style={styles.cardText}>Uploaded: {item.time_ago_uploaded}</Text>
        </View>
      ))}

      <Text style={styles.sectionTitle}>Active Transactions</Text>
      {active.length === 0 ? <Text style={styles.mutedText}>No active transactions.</Text> : null}
      {active.map((item) => (
        <View key={`active-${item.id}`} style={styles.card}>
          <Text style={styles.cardTitle}>{item.property_address || "No address"}</Text>
          <Text style={styles.cardText}>
            {item.agent_name} • {item.agent_phone}
          </Text>
          <Text style={styles.cardText}>{item.days_until_label}</Text>
          <Text style={styles.cardText}>Next: {item.next_deadline_label}</Text>
          <Text style={styles.cardText}>Payments: {item.payment_summary}</Text>
        </View>
      ))}
    </View>
  );
}

function ChecklistTab({ checklistData, onRefresh, onTaskComplete, onCallComplete, onOpenPhone }) {
  const summary = checklistData?.summary || {};
  const calls = checklistData?.calls_to_make || [];
  const overdueTasks = checklistData?.overdue_tasks || [];
  const todayTasks = checklistData?.due_today_tasks || [];

  return (
    <View>
      <Pressable style={styles.buttonSecondary} onPress={onRefresh}>
        <Text style={styles.buttonSecondaryText}>Refresh Checklist</Text>
      </Pressable>

      <View style={styles.kpiRow}>
        <KpiCard label="Overdue" value={summary.overdue_count || 0} />
        <KpiCard label="Due Today" value={summary.due_today_count || 0} />
        <KpiCard label="Calls" value={summary.calls_count || 0} />
      </View>

      <Text style={styles.sectionTitle}>Calls to Make</Text>
      {calls.length === 0 ? <Text style={styles.mutedText}>No calls required right now.</Text> : null}
      {calls.map((callItem) => (
        <View key={`call-${callItem.deadline_id}`} style={styles.card}>
          <Text style={styles.cardTitle}>{callItem.property_address || "No address"}</Text>
          <Text style={styles.cardText}>
            {callItem.deadline_label} • {callItem.days_label}
          </Text>
          <Text style={styles.cardText}>Call: {callItem.contact_phone || "N/A"}</Text>
          <Text style={styles.cardText}>{callItem.call_script}</Text>
          <View style={styles.inlineRow}>
            <Pressable style={styles.buttonTiny} onPress={() => onOpenPhone(callItem.phone_link)}>
              <Text style={styles.buttonTinyText}>Call</Text>
            </Pressable>
            <Pressable style={styles.buttonTiny} onPress={() => onCallComplete(callItem.deadline_id)}>
              <Text style={styles.buttonTinyText}>Mark Done</Text>
            </Pressable>
          </View>
        </View>
      ))}

      <Text style={styles.sectionTitle}>Overdue Tasks</Text>
      {overdueTasks.length === 0 ? <Text style={styles.mutedText}>No overdue tasks.</Text> : null}
      {overdueTasks.map((task) => (
        <View key={`overdue-${task.task_id}`} style={styles.card}>
          <Text style={styles.cardTitle}>{task.task_description}</Text>
          <Text style={styles.cardText}>{task.property_address}</Text>
          <Text style={styles.cardText}>Due: {task.due_label}</Text>
          <Pressable style={styles.buttonTiny} onPress={() => onTaskComplete(task.task_id)}>
            <Text style={styles.buttonTinyText}>Complete</Text>
          </Pressable>
        </View>
      ))}

      <Text style={styles.sectionTitle}>Due Today</Text>
      {todayTasks.length === 0 ? <Text style={styles.mutedText}>No tasks due today.</Text> : null}
      {todayTasks.map((task) => (
        <View key={`today-${task.task_id}`} style={styles.card}>
          <Text style={styles.cardTitle}>{task.task_description}</Text>
          <Text style={styles.cardText}>{task.property_address}</Text>
          <Pressable style={styles.buttonTiny} onPress={() => onTaskComplete(task.task_id)}>
            <Text style={styles.buttonTinyText}>Complete</Text>
          </Pressable>
        </View>
      ))}
    </View>
  );
}

function DocumentsTab({ transactionId, setTransactionId, documentsPayload, onRefresh, onOpenUrl }) {
  const docs = documentsPayload?.documents || [];
  const missing = documentsPayload?.missing_required_documents || [];

  return (
    <View>
      <Text style={styles.label}>Transaction ID</Text>
      <TextInput
        style={styles.input}
        value={transactionId}
        onChangeText={setTransactionId}
        keyboardType="numeric"
        placeholder="e.g. 12"
      />
      <Pressable style={styles.buttonSecondary} onPress={onRefresh}>
        <Text style={styles.buttonSecondaryText}>Load Documents</Text>
      </Pressable>

      <Text style={styles.sectionTitle}>Documents</Text>
      {docs.length === 0 ? <Text style={styles.mutedText}>No documents loaded.</Text> : null}
      {docs.map((doc) => (
        <View key={`doc-${doc.id}`} style={styles.card}>
          <Text style={styles.cardTitle}>{doc.document_type_label}</Text>
          <Text style={styles.cardText}>{doc.filename}</Text>
          <Text style={styles.cardText}>Uploaded: {doc.uploaded_at || "Unknown"}</Text>
          <View style={styles.inlineRow}>
            <Pressable style={styles.buttonTiny} onPress={() => onOpenUrl(doc.view_url)}>
              <Text style={styles.buttonTinyText}>View</Text>
            </Pressable>
            <Pressable style={styles.buttonTiny} onPress={() => onOpenUrl(doc.download_url)}>
              <Text style={styles.buttonTinyText}>Download</Text>
            </Pressable>
          </View>
        </View>
      ))}

      <Text style={styles.sectionTitle}>Missing Required</Text>
      {missing.length === 0 ? <Text style={styles.mutedText}>No missing required documents.</Text> : null}
      {missing.map((name) => (
        <Text key={name} style={styles.cardText}>
          • {name.replace(/_/g, " ")}
        </Text>
      ))}
    </View>
  );
}

function CommunicationsTab({ form, setForm, communications, onSubmit, onLoad }) {
  const setField = (field, value) => {
    setForm((prev) => ({ ...prev, [field]: value }));
  };

  return (
    <View>
      <Text style={styles.label}>Transaction ID</Text>
      <TextInput
        style={styles.input}
        value={form.transactionId}
        onChangeText={(value) => setField("transactionId", value)}
        keyboardType="numeric"
        placeholder="e.g. 12"
      />

      <Text style={styles.label}>Communication Type</Text>
      <TextInput
        style={styles.input}
        value={form.communicationType}
        onChangeText={(value) => setField("communicationType", value)}
        placeholder="phone_call | email | text"
      />

      <Text style={styles.label}>Contact Party</Text>
      <TextInput
        style={styles.input}
        value={form.contactParty}
        onChangeText={(value) => setField("contactParty", value)}
        placeholder="agent | lender | title_company"
      />

      <Text style={styles.label}>Contact Name</Text>
      <TextInput
        style={styles.input}
        value={form.contactName}
        onChangeText={(value) => setField("contactName", value)}
        placeholder="Name (optional)"
      />

      <Text style={styles.label}>Summary</Text>
      <TextInput
        style={[styles.input, styles.inputLarge]}
        value={form.summary}
        onChangeText={(value) => setField("summary", value)}
        multiline
      />

      <Text style={styles.label}>Outcome</Text>
      <TextInput
        style={[styles.input, styles.inputLarge]}
        value={form.outcome}
        onChangeText={(value) => setField("outcome", value)}
        multiline
      />

      <Text style={styles.label}>Follow-up Date (YYYY-MM-DD)</Text>
      <TextInput
        style={styles.input}
        value={form.followUpDate}
        onChangeText={(value) => setField("followUpDate", value)}
        placeholder="optional"
      />

      <View style={styles.inlineRow}>
        <Pressable style={styles.buttonTiny} onPress={onSubmit}>
          <Text style={styles.buttonTinyText}>Log Communication</Text>
        </Pressable>
        <Pressable style={styles.buttonTiny} onPress={onLoad}>
          <Text style={styles.buttonTinyText}>Load History</Text>
        </Pressable>
      </View>

      <Text style={styles.sectionTitle}>Recent Communications</Text>
      {communications.length === 0 ? <Text style={styles.mutedText}>No communications loaded.</Text> : null}
      {communications.map((item) => (
        <View key={`comm-${item.id}`} style={styles.card}>
          <Text style={styles.cardTitle}>
            {item.communication_type} • {item.contact_party}
          </Text>
          <Text style={styles.cardText}>{item.summary}</Text>
          <Text style={styles.cardText}>By: {item.logged_by}</Text>
          <Text style={styles.cardText}>At: {item.created_at}</Text>
        </View>
      ))}
    </View>
  );
}

function KpiCard({ label, value }) {
  return (
    <View style={styles.kpiCard}>
      <Text style={styles.kpiValue}>{value}</Text>
      <Text style={styles.kpiLabel}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: "#f8fafc",
  },
  content: {
    padding: 16,
    paddingBottom: 80,
    gap: 10,
  },
  topBar: {
    paddingHorizontal: 16,
    paddingTop: 10,
    paddingBottom: 6,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    backgroundColor: "#ffffff",
    borderBottomWidth: 1,
    borderBottomColor: "#e2e8f0",
  },
  tabBar: {
    maxHeight: 54,
    paddingHorizontal: 12,
    backgroundColor: "#ffffff",
    borderBottomWidth: 1,
    borderBottomColor: "#e2e8f0",
  },
  tabButton: {
    paddingHorizontal: 14,
    paddingVertical: 10,
    marginHorizontal: 4,
    marginVertical: 8,
    borderRadius: 999,
    backgroundColor: "#e2e8f0",
  },
  tabButtonActive: {
    backgroundColor: "#2563eb",
  },
  tabButtonText: {
    color: "#0f172a",
    fontSize: 13,
    fontWeight: "600",
  },
  tabButtonTextActive: {
    color: "#ffffff",
  },
  title: {
    fontSize: 28,
    fontWeight: "700",
    color: "#0f172a",
    marginBottom: 4,
  },
  titleSmall: {
    fontSize: 18,
    fontWeight: "700",
    color: "#0f172a",
  },
  subtitle: {
    color: "#475569",
    marginBottom: 14,
  },
  label: {
    fontWeight: "600",
    color: "#0f172a",
    marginTop: 6,
  },
  input: {
    borderWidth: 1,
    borderColor: "#cbd5e1",
    borderRadius: 10,
    backgroundColor: "#ffffff",
    paddingHorizontal: 12,
    paddingVertical: 10,
    color: "#0f172a",
  },
  inputLarge: {
    minHeight: 84,
    textAlignVertical: "top",
  },
  button: {
    marginTop: 14,
    backgroundColor: "#2563eb",
    borderRadius: 10,
    paddingVertical: 12,
    alignItems: "center",
  },
  buttonText: {
    color: "#ffffff",
    fontWeight: "700",
    fontSize: 15,
  },
  buttonSecondary: {
    alignSelf: "flex-start",
    borderRadius: 10,
    backgroundColor: "#1d4ed8",
    paddingHorizontal: 12,
    paddingVertical: 8,
    marginBottom: 8,
  },
  buttonSecondaryText: {
    color: "#ffffff",
    fontWeight: "600",
  },
  buttonTiny: {
    borderRadius: 8,
    backgroundColor: "#2563eb",
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  buttonTinyText: {
    color: "#ffffff",
    fontWeight: "600",
    fontSize: 12,
  },
  sectionTitle: {
    marginTop: 12,
    marginBottom: 6,
    fontWeight: "700",
    fontSize: 17,
    color: "#0f172a",
  },
  card: {
    borderWidth: 1,
    borderColor: "#dbeafe",
    backgroundColor: "#ffffff",
    borderRadius: 12,
    padding: 12,
    marginBottom: 8,
    gap: 3,
  },
  cardTitle: {
    fontSize: 15,
    fontWeight: "700",
    color: "#0f172a",
  },
  cardText: {
    color: "#334155",
  },
  mutedText: {
    color: "#64748b",
  },
  inlineRow: {
    flexDirection: "row",
    gap: 8,
    marginTop: 8,
    flexWrap: "wrap",
  },
  loader: {
    marginTop: 10,
  },
  errorText: {
    color: "#b91c1c",
    fontWeight: "600",
    marginTop: 8,
    marginHorizontal: 16,
  },
  linkText: {
    color: "#1d4ed8",
    fontWeight: "600",
  },
  kpiRow: {
    flexDirection: "row",
    flexWrap: "wrap",
    gap: 8,
    marginVertical: 8,
  },
  kpiCard: {
    minWidth: 95,
    paddingHorizontal: 10,
    paddingVertical: 10,
    borderRadius: 10,
    borderWidth: 1,
    borderColor: "#dbeafe",
    backgroundColor: "#ffffff",
  },
  kpiValue: {
    fontSize: 21,
    fontWeight: "700",
    color: "#0f172a",
  },
  kpiLabel: {
    color: "#475569",
    fontSize: 12,
  },
});
