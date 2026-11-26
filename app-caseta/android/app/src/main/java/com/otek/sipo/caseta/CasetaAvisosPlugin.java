package com.otek.sipo.caseta;

import android.Manifest;
import android.os.Build;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

/** Puente para la web de Caseta: CasetaAvisos.iniciar({ url }) y CasetaAvisos.detener(). */
@CapacitorPlugin(
        name = "CasetaAvisos",
        permissions = {@Permission(alias = "notificaciones", strings = {Manifest.permission.POST_NOTIFICATIONS})}
)
public class CasetaAvisosPlugin extends Plugin {

    @PluginMethod
    public void iniciar(PluginCall call) {
        String url = call.getString("url");
        if (url == null || !url.startsWith("https://")) {
            call.reject("URL de avisos no válida");
            return;
        }
        if (Build.VERSION.SDK_INT >= 33 && getPermissionState("notificaciones") != PermissionState.GRANTED) {
            requestPermissionForAlias("notificaciones", call, "despuesDePermiso");
            return;
        }
        arrancar(call, url);
    }

    @PermissionCallback
    private void despuesDePermiso(PluginCall call) {
        // Aunque niegue las notificaciones, el servicio sigue y la app muestra los avisos al abrirse
        arrancar(call, call.getString("url"));
    }

    private void arrancar(PluginCall call, String url) {
        CasetaAvisosService.iniciar(getContext(), url);
        JSObject r = new JSObject();
        r.put("activo", true);
        r.put("notificaciones", Build.VERSION.SDK_INT < 33 || getPermissionState("notificaciones") == PermissionState.GRANTED);
        call.resolve(r);
    }

    @PluginMethod
    public void detener(PluginCall call) {
        CasetaAvisosService.detener(getContext());
        call.resolve();
    }
}
