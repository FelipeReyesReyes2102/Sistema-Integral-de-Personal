package com.otek.sipo.caseta;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;
import android.webkit.CookieManager;

import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Set;
import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;

/**
 * Servicio en primer plano de la app de Caseta: cada minuto pide a SIP-O los permisos por horas aprobados
 * (GET /api/caseta/avisos, con la cookie de sesión de la app) y avisa de los nuevos. Los de HOY van con prioridad alta.
 * Todo queda en la red interna: no usa servicios externos de notificaciones.
 */
public class CasetaAvisosService extends Service {
    static final String EXTRA_URL = "url";
    static final String CANAL_SERVICIO = "caseta_servicio";
    static final String CANAL_HOY = "caseta_hoy";
    static final String CANAL_PROXIMOS = "caseta_proximos";
    static final int ID_SERVICIO = 1;
    private static final String PREFS = "caseta_avisos";
    private static final long INTERVALO_SEG = 60;

    private ScheduledExecutorService reloj;
    private PowerManager.WakeLock wakeLock;
    private String url;

    static void iniciar(Context ctx, String url) {
        ctx.getSharedPreferences(PREFS, MODE_PRIVATE).edit().putString("url", url).putBoolean("activo", true).apply();
        Intent i = new Intent(ctx, CasetaAvisosService.class).putExtra(EXTRA_URL, url);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) ctx.startForegroundService(i);
        else ctx.startService(i);
    }

    static void detener(Context ctx) {
        ctx.getSharedPreferences(PREFS, MODE_PRIVATE).edit().putBoolean("activo", false).remove("vistos").apply();
        ctx.stopService(new Intent(ctx, CasetaAvisosService.class));
    }

    @Override
    public void onCreate() {
        super.onCreate();
        crearCanales(this);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        url = intent != null && intent.getStringExtra(EXTRA_URL) != null ? intent.getStringExtra(EXTRA_URL) : prefs.getString("url", null);
        Notification fija = new NotificationCompat.Builder(this, CANAL_SERVICIO)
                .setSmallIcon(R.drawable.ic_stat_caseta)
                .setContentTitle("Caseta activa")
                .setContentText("Revisando permisos nuevos cada minuto")
                .setContentIntent(abrirApp())
                .setOngoing(true)
                .setPriority(NotificationCompat.PRIORITY_MIN)
                .build();
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(ID_SERVICIO, fija, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(ID_SERVICIO, fija);
        }
        if (url == null) {
            stopSelf();
            return START_NOT_STICKY;
        }
        if (wakeLock == null) {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            wakeLock = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "sipo:caseta-avisos");
            wakeLock.setReferenceCounted(false);
            wakeLock.acquire();
        }
        if (reloj == null) {
            reloj = Executors.newSingleThreadScheduledExecutor();
            reloj.scheduleWithFixedDelay(this::revisar, 0, INTERVALO_SEG, TimeUnit.SECONDS);
        }
        return START_STICKY;
    }

    private void revisar() {
        HttpURLConnection con = null;
        try {
            con = (HttpURLConnection) new URL(url).openConnection();
            con.setConnectTimeout(15000);
            con.setReadTimeout(15000);
            con.setRequestProperty("Accept", "application/json");
            String cookie = CookieManager.getInstance().getCookie(url);
            if (cookie != null) con.setRequestProperty("Cookie", cookie);
            int codigo = con.getResponseCode();
            if (codigo == 401 || codigo == 403) {
                avisar(CANAL_PROXIMOS, 2, "Caseta: sesión cerrada", "Abre la app y vuelve a entrar para seguir recibiendo avisos.", true);
                return;
            }
            if (codigo != 200) return;
            StringBuilder sb = new StringBuilder();
            try (BufferedReader r = new BufferedReader(new InputStreamReader(con.getInputStream(), StandardCharsets.UTF_8))) {
                String linea;
                while ((linea = r.readLine()) != null) sb.append(linea);
            }
            JSONArray avisos = new JSONObject(sb.toString()).getJSONArray("avisos");
            procesar(avisos);
        } catch (Exception ignorado) {
            // Sin red interna por el momento: se reintenta en el siguiente minuto
        } finally {
            if (con != null) con.disconnect();
        }
    }

    private void procesar(JSONArray avisos) throws Exception {
        SharedPreferences prefs = getSharedPreferences(PREFS, MODE_PRIVATE);
        boolean primera = !prefs.contains("vistos");
        Set<String> vistos = new HashSet<>(prefs.getStringSet("vistos", new HashSet<>()));
        List<JSONObject> hoy = new ArrayList<>();
        List<JSONObject> proximos = new ArrayList<>();
        Set<String> actuales = new HashSet<>();
        for (int i = 0; i < avisos.length(); i++) {
            JSONObject a = avisos.getJSONObject(i);
            String id = String.valueOf(a.getLong("id"));
            actuales.add(id);
            if (!vistos.contains(id)) (a.optBoolean("es_hoy") ? hoy : proximos).add(a);
        }
        // Se guardan solo los vigentes, para que la lista no crezca sin límite
        prefs.edit().putStringSet("vistos", actuales).apply();
        if (primera) return;  // al iniciar solo se toma nota de los que ya existían
        if (!hoy.isEmpty()) {
            avisar(CANAL_HOY, 10, hoy.size() == 1 ? "Nuevo permiso para HOY" : hoy.size() + " permisos nuevos para HOY", texto(hoy, true), false);
        }
        if (!proximos.isEmpty()) {
            avisar(CANAL_PROXIMOS, 11, proximos.size() == 1 ? "Nuevo permiso aprobado" : proximos.size() + " permisos nuevos aprobados", texto(proximos, false), false);
        }
    }

    private String texto(List<JSONObject> lista, boolean hoy) {
        StringBuilder sb = new StringBuilder();
        for (JSONObject a : lista) {
            if (sb.length() > 0) sb.append('\n');
            String fecha = a.optString("fecha");
            if (!hoy && fecha.length() == 10) sb.append(fecha.substring(8, 10)).append('/').append(fecha.substring(5, 7)).append(' ');
            sb.append(a.optString("hora")).append(" · ").append(a.optString("nombre")).append(" — ").append(a.optString("tipo_nombre"));
        }
        return sb.toString();
    }

    private void avisar(String canal, int id, String titulo, String cuerpo, boolean silencioso) {
        NotificationCompat.Builder b = new NotificationCompat.Builder(this, canal)
                .setSmallIcon(R.drawable.ic_stat_caseta)
                .setContentTitle(titulo)
                .setContentText(cuerpo.split("\n")[0])
                .setStyle(new NotificationCompat.BigTextStyle().bigText(cuerpo))
                .setContentIntent(abrirApp())
                .setAutoCancel(true)
                .setOnlyAlertOnce(silencioso)
                .setCategory(NotificationCompat.CATEGORY_REMINDER)
                .setPriority(CANAL_HOY.equals(canal) ? NotificationCompat.PRIORITY_HIGH : NotificationCompat.PRIORITY_DEFAULT);
        try {
            NotificationManagerCompat.from(this).notify(id, b.build());
        } catch (SecurityException sinPermiso) {
            // El usuario no permitió notificaciones; la app las muestra al abrirse
        }
    }

    private PendingIntent abrirApp() {
        Intent i = new Intent(this, MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        return PendingIntent.getActivity(this, 0, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
    }

    static void crearCanales(Context ctx) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationManager nm = ctx.getSystemService(NotificationManager.class);
        NotificationChannel servicio = new NotificationChannel(CANAL_SERVICIO, "Servicio de caseta", NotificationManager.IMPORTANCE_MIN);
        servicio.setDescription("Aviso fijo mientras la app revisa permisos nuevos");
        NotificationChannel hoy = new NotificationChannel(CANAL_HOY, "Permisos de hoy", NotificationManager.IMPORTANCE_HIGH);
        hoy.setDescription("Permisos aprobados para hoy: quién sale o entra y a qué hora");
        hoy.enableVibration(true);
        NotificationChannel proximos = new NotificationChannel(CANAL_PROXIMOS, "Permisos de los próximos días", NotificationManager.IMPORTANCE_DEFAULT);
        proximos.setDescription("Permisos aprobados para los próximos días");
        nm.createNotificationChannel(servicio);
        nm.createNotificationChannel(hoy);
        nm.createNotificationChannel(proximos);
    }

    @Override
    public void onDestroy() {
        if (reloj != null) reloj.shutdownNow();
        reloj = null;
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        wakeLock = null;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
